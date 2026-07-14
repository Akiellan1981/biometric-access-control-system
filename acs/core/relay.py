"""Optional relay output to drive a lock/strike (spec FR-3.5 / HW-9)."""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class Relay:
    def __init__(self, cfg):
        self.enabled = bool(cfg.get("relay.enabled", False))
        self.hold = float(cfg.get("relay.hold_seconds", 3))
        self._dev = None
        if not self.enabled:
            return
        try:
            from gpiozero import OutputDevice
            self._dev = OutputDevice(
                cfg.get("relay.gpio_pin", 17),
                active_high=bool(cfg.get("relay.active_high", True)),
                initial_value=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("relay disabled (gpiozero unavailable: %s)", e)
            self.enabled = False

    def pulse(self):
        """Energize the relay for hold_seconds, in a background thread."""
        if not self.enabled:
            log.info("[relay] (disabled) would unlock for %ss", self.hold)
            return
        threading.Thread(target=self._pulse, daemon=True).start()

    def _pulse(self):
        try:
            self._dev.on()
            time.sleep(self.hold)
        finally:
            self._dev.off()
