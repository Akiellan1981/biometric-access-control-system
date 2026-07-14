"""In-memory mock sensor — lets the whole system run/test without hardware."""
from __future__ import annotations

import logging
import queue
from typing import Optional

from .base import FingerprintSensor, FingerMatch

log = logging.getLogger(__name__)


class MockFingerprint(FingerprintSensor):
    """Use simulate_touch(slot) to make the next search() return that match."""

    def __init__(self, default_confidence: int = 90):
        self._slots: set[int] = set()
        self._next = 0
        self._touches: "queue.Queue[FingerMatch]" = queue.Queue()
        self._default_conf = default_confidence

    def simulate_touch(self, slot: int, confidence: Optional[int] = None):
        self._touches.put(FingerMatch(slot, confidence or self._default_conf))

    def search(self) -> Optional[FingerMatch]:
        try:
            return self._touches.get_nowait()
        except queue.Empty:
            return None

    def enroll(self) -> int:
        slot = self._next
        self._next += 1
        self._slots.add(slot)
        log.info("mock fingerprint enrolled at slot %d", slot)
        return slot

    def delete(self, slot: int) -> bool:
        self._slots.discard(slot)
        return True

    def count(self) -> int:
        return len(self._slots)
