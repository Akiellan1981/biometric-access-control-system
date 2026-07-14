"""Status LED + lamp + ambient-light handling, with mocks so it runs on a PC.

- Status LED: ON while the camera is awake/checking, OFF in sleep — a visible
  "camera is working" cue next to the lens.
- Lamp: turns ON when the scene is too dark for reliable recognition, OFF when
  bright again (hysteresis). Brightness is read from the camera frame itself, so
  no extra light sensor is required (a GPIO digital sensor can be added later).

Everything is behind enable flags + a gpio/mock driver, mirroring relay.py /
motion.py, so the device fails safe and the dev PC is unaffected.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def frame_brightness(frame) -> float:
    """Mean luminance (0-255) of a BGR frame; 0.0 if it can't be measured."""
    if frame is None:
        return 0.0
    try:
        import cv2
        return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
    except Exception:  # noqa: BLE001 - fall back to raw mean
        try:
            return float(frame.mean())
        except Exception:  # noqa: BLE001
            return 0.0


class _MockOut:
    def __init__(self, name): self.name = name; self.state = False
    def on(self): self.state = True
    def off(self): self.state = False
    def close(self): self.off()


class _GpioOut:
    def __init__(self, pin: int, active_high: bool = True):
        from gpiozero import LED
        self._d = LED(pin, active_high=active_high)
        self.state = False
    def on(self): self._d.on(); self.state = True
    def off(self): self._d.off(); self.state = False
    def close(self):
        try:
            self._d.close()
        except Exception:  # noqa: BLE001
            pass


def _make_out(cfg, prefix: str, name: str):
    if not bool(cfg.get(f"{prefix}.enabled", False)):
        return _MockOut(name)                       # disabled -> harmless no-op
    if cfg.get(f"{prefix}.driver", "gpio") == "gpio":
        try:
            return _GpioOut(int(cfg.get(f"{prefix}.pin", 0)),
                            bool(cfg.get(f"{prefix}.active_high", True)))
        except Exception as e:  # noqa: BLE001 - missing lib/hardware -> mock, stay safe
            log.warning("%s gpio unavailable (%s) -> mock", name, e)
    return _MockOut(name)


class Indicators:
    def __init__(self, cfg):
        self.led = _make_out(cfg, "status_led", "status-led")
        self.lamp = _make_out(cfg, "lamp", "lamp")
        self.dark_thr = float(cfg.get("lamp.dark_threshold", 60))
        self.margin = float(cfg.get("lamp.bright_margin", 15))

    def wake(self):
        self.led.on()

    def sleep(self):
        self.led.off()
        self.lamp.off()

    def update_light(self, frame) -> bool:
        """Hysteresis lamp control from frame brightness. Returns lamp ON state."""
        b = frame_brightness(frame)
        if b and b < self.dark_thr:
            self.lamp.on()
        elif b > self.dark_thr + self.margin:
            self.lamp.off()
        return self.lamp.state

    def close(self):
        self.led.close()
        self.lamp.close()
