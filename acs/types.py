"""Shared data types passed between pipeline threads and the decision engine."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Method(str, Enum):
    FACE = "face"
    FINGERPRINT = "fingerprint"


class Result(str, Enum):
    GRANTED = "granted"
    DENIED_UNKNOWN = "denied-unknown"   # real, unrecognized person
    DENIED_SPOOF = "denied-spoof"       # liveness failed (photo/screen attack)
    DENIED_FINGER = "denied-finger"     # finger read but did not resolve to a person


@dataclass
class Detection:
    """One detected face (YuNet output)."""
    x: int
    y: int
    w: int
    h: int
    score: float
    landmarks: object = None   # np.ndarray (5,2) or None
    raw: object = None         # original YuNet row, needed by SFace.alignCrop

    @property
    def box(self):
        return (self.x, self.y, self.w, self.h)


@dataclass
class Candidate:
    """Emitted by a pipeline thread onto the shared queue for the decision engine."""
    person_id: Optional[int]
    method: Method
    score: float = 0.0
    is_live: bool = True
    name: Optional[str] = None
    frame: object = None       # numpy BGR frame for intruder capture (face path only)
    ts: float = field(default_factory=time.time)
