"""Fingerprint driver interface + factory (spec FR-2.2)."""
from __future__ import annotations

import logging

from .base import FingerprintSensor, FingerMatch

log = logging.getLogger(__name__)


def create_sensor(cfg) -> FingerprintSensor:
    driver = (cfg.get("fingerprint.driver") or "mock").lower()
    if driver == "pyfingerprint":
        try:
            from .pyfp import PyFingerprint
            return PyFingerprint(
                port=cfg.get("fingerprint.port"),
                baudrate=cfg.get("fingerprint.baudrate", 57600),
                confidence_min=cfg.get("fingerprint.confidence_min", 50),
            )
        except Exception as e:  # noqa: BLE001 - fall back so the device still runs
            log.error("pyfingerprint unavailable (%s); falling back to mock", e)
    from .mock import MockFingerprint
    return MockFingerprint()


__all__ = ["FingerprintSensor", "FingerMatch", "create_sensor"]
