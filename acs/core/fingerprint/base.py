"""Abstract fingerprint sensor interface. Matching happens ON the sensor."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class FingerMatch:
    slot: int          # template id on the sensor
    confidence: int    # sensor-reported match confidence


class FingerprintSensor(ABC):
    @abstractmethod
    def search(self) -> Optional[FingerMatch]:
        """Non-blocking-ish: return a match if a finger is present & recognized, else None."""

    @abstractmethod
    def enroll(self) -> int:
        """Enroll the currently presented finger; return the assigned slot id."""

    @abstractmethod
    def delete(self, slot: int) -> bool:
        ...

    @abstractmethod
    def count(self) -> int:
        ...

    def close(self) -> None:
        pass
