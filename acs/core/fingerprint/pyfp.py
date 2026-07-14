"""Real R307/R503-class sensor via pyfingerprint (UART). Pi-only."""
from __future__ import annotations

import logging
import time
from typing import Optional

from .base import FingerprintSensor, FingerMatch

log = logging.getLogger(__name__)


class PyFingerprint(FingerprintSensor):
    def __init__(self, port: str, baudrate: int = 57600, confidence_min: int = 50):
        from pyfingerprint.pyfingerprint import PyFingerprint as _PF
        self._pf = _PF(port, baudrate, 0xFFFFFFFF, 0x00000000)
        if not self._pf.verifyPassword():
            raise RuntimeError("fingerprint sensor password verification failed")
        self.confidence_min = confidence_min

    def search(self) -> Optional[FingerMatch]:
        if not self._pf.readImage():        # returns False if no finger present
            return None
        self._pf.convertImage(0x01)
        slot, score = self._pf.searchTemplate()
        if slot == -1 or score < self.confidence_min:
            return None
        return FingerMatch(slot, int(score))

    def enroll(self, timeout_s: float = 15.0) -> int:
        """Two-pass enrollment. Blocks until a finger is read (or timeout)."""
        self._wait_for_finger(timeout_s)
        self._pf.convertImage(0x01)
        log.info("remove finger...")
        time.sleep(2)
        self._wait_for_finger(timeout_s)
        self._pf.convertImage(0x02)
        if self._pf.compareCharacteristics() == 0:
            raise RuntimeError("fingers do not match; retry enrollment")
        self._pf.createTemplate()
        slot = self._pf.storeTemplate()
        return int(slot)

    def delete(self, slot: int) -> bool:
        return bool(self._pf.deleteTemplate(slot))

    def count(self) -> int:
        return int(self._pf.getTemplateCount())

    def _wait_for_finger(self, timeout_s: float):
        start = time.time()
        while not self._pf.readImage():
            if time.time() - start > timeout_s:
                raise TimeoutError("no finger detected")
            time.sleep(0.1)
