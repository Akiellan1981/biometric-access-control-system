"""Motion (PIR/IR) sensor — wake the camera only when someone is present.

On the Pi a PIR's digital OUT is wired to a BCM GPIO pin; we read it via gpiozero
(preferred) or RPi.GPIO. The mock driver always reports motion, so the system runs
unchanged on a PC. Used by the device pipeline to power the camera down when idle.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class MotionSensor(ABC):
    @abstractmethod
    def motion(self) -> bool:
        """True if a person/motion is currently detected."""

    def close(self) -> None:
        pass


class MockMotion(MotionSensor):
    """Always 'present' — keeps dev/PC behaviour unchanged (camera always awake)."""
    def motion(self) -> bool:
        return True


class PirGpio(MotionSensor):
    def __init__(self, pin: int):
        self._mode = None
        try:
            from gpiozero import MotionSensor as _PIR
            self._dev = _PIR(pin)
            self._mode = "gpiozero"
        except Exception:
            import RPi.GPIO as GPIO   # noqa: N814
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.IN)
            self._GPIO = GPIO
            self._pin = pin
            self._mode = "rpi"
        log.info("PIR motion sensor on GPIO %d (%s)", pin, self._mode)

    def motion(self) -> bool:
        if self._mode == "gpiozero":
            return bool(self._dev.motion_detected)
        return bool(self._GPIO.input(self._pin))

    def close(self) -> None:
        try:
            if self._mode == "rpi":
                self._GPIO.cleanup(self._pin)
        except Exception:  # noqa: BLE001
            pass


def create_motion(cfg) -> MotionSensor:
    if not cfg.get("motion.enabled", False):
        return MockMotion()
    driver = (cfg.get("motion.driver") or "mock").lower()
    if driver == "gpio":
        try:
            return PirGpio(int(cfg.get("motion.pin", 4)))
        except Exception as e:  # noqa: BLE001 - fall back so the device still runs
            log.error("PIR unavailable (%s); using mock (camera always awake)", e)
    return MockMotion()
