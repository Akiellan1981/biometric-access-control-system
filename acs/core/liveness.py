"""Anti-spoofing / liveness (spec FR-1.3).

Primary : Silent-Face MiniFASNet ensemble (ONNX Runtime) — defeats printed and
          phone-screen photos.
Secondary: eye-blink via MediaPipe FaceMesh (EAR) — an independent live signal
          tracked across frames.

Both backends import lazily. If the primary model/runtime is missing, the caller
decides policy via `available` (fail-open in dev_mode, fail-closed in production).
"""
from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

# MediaPipe FaceMesh indices for the six eye points used by the EAR formula.
_LEFT_EYE = [33, 160, 158, 133, 153, 144]
_RIGHT_EYE = [362, 385, 387, 263, 373, 380]


def _expand_box(x, y, w, h, scale, img_w, img_h):
    cx, cy = x + w / 2, y + h / 2
    side = max(w, h) * scale
    nx, ny = int(cx - side / 2), int(cy - side / 2)
    nx2, ny2 = int(cx + side / 2), int(cy + side / 2)
    return max(0, nx), max(0, ny), min(img_w, nx2), min(img_h, ny2)


class MiniFASNet:
    """Ensemble of MiniFASNet ONNX models (3-class: 0=fake2d,1=real,2=fake3d-ish)."""

    def __init__(self, models_dir: str | Path, model_specs, live_thr: float = 0.90):
        import numpy as np
        import onnxruntime as ort
        self._np = np
        self.live_thr = live_thr
        self._sessions = []
        for scale, fname in model_specs:
            path = Path(models_dir) / fname
            if not path.exists():
                raise FileNotFoundError(f"liveness model missing: {path}")
            sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self._sessions.append((float(scale), sess))
        if not self._sessions:
            raise RuntimeError("no liveness models configured")

    def score(self, frame, det) -> float:
        """Return P(real) averaged across the ensemble (0..1)."""
        import cv2
        np = self._np
        h, w = frame.shape[:2]
        probs = np.zeros(3, dtype="float32")
        for scale, sess in self._sessions:
            x1, y1, x2, y2 = _expand_box(det.x, det.y, det.w, det.h, scale, w, h)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            crop = cv2.resize(crop, (80, 80)).astype("float32")
            blob = np.transpose(crop, (2, 0, 1))[None] / 255.0
            out = sess.run(None, {sess.get_inputs()[0].name: blob.astype("float32")})[0][0]
            probs += _softmax(out, np)
        probs /= len(self._sessions)
        return float(probs[1])   # class 1 == real

    def is_live(self, frame, det) -> tuple[bool, float]:
        s = self.score(frame, det)
        return s >= self.live_thr, s


class BlinkDetector:
    """Tracks EAR across frames; reports a blink when the eye closes then reopens."""

    def __init__(self, models_dir, ear_thr: float = 0.21, window: int = 30):
        from acs.core.facemesh import FaceLandmarks
        self._lm = FaceLandmarks(models_dir)
        self.ear_thr = ear_thr
        self._states = deque(maxlen=window)

    def update(self, frame) -> bool:
        """Feed a frame; return True if a blink has occurred within the window."""
        pts3 = self._lm.detect(frame)
        if not pts3:
            return self._has_blink()
        h, w = frame.shape[:2]
        pts = [(int(p[0] * w), int(p[1] * h)) for p in pts3]
        ear = (_ear(pts, _LEFT_EYE) + _ear(pts, _RIGHT_EYE)) / 2.0
        self._states.append(ear < self.ear_thr)   # True == eye closed
        return self._has_blink()

    def _has_blink(self) -> bool:
        # a closed frame followed by an open frame within the window = a blink
        s = list(self._states)
        return any(s[i] and not s[i + 1] for i in range(len(s) - 1))


class PassiveLiveness:
    """Single-frame liveness from MediaPipe FaceMesh, for dev/laptop use when the
    MiniFASNet ONNX weights are not present.

    Key cue: a printed photo or a phone/laptop screen is FLAT, so all 468 mesh
    landmarks lie on one plane and their depth (z) barely varies. A real face has
    a protruding nose and recessed eyes, so the depth spread is large. Blink (EAR)
    is used as a second confirming signal.
    """

    def __init__(self, models_dir, depth_thr: float = 0.10, ear_thr: float = 0.21, window: int = 12):
        from acs.core.facemesh import FaceLandmarks
        self._lm = FaceLandmarks(models_dir)
        self.depth_thr = depth_thr
        self.ear_thr = ear_thr
        self._states = deque(maxlen=window)

    def is_live(self, frame, det=None) -> tuple[bool, float]:
        pts3 = self._lm.detect(frame)
        if not pts3:
            return False, 0.0
        xs = [p[0] for p in pts3]
        zs = [p[2] for p in pts3]
        face_w = (max(xs) - min(xs)) or 1e-6
        depth_spread = (max(zs) - min(zs)) / face_w   # normalized by face width

        # blink within the recent window = strong liveness signal
        h, w = frame.shape[:2]
        pts = [(int(p[0] * w), int(p[1] * h)) for p in pts3]
        ear = (_ear(pts, _LEFT_EYE) + _ear(pts, _RIGHT_EYE)) / 2.0
        self._states.append(ear < self.ear_thr)
        s = list(self._states)
        blinked = any(s[i] and not s[i + 1] for i in range(len(s) - 1))

        live = depth_spread >= self.depth_thr or blinked
        return live, round(float(depth_spread), 3)


class LivenessChecker:
    """Best-available liveness backend.

    Production (Pi): MiniFASNet ONNX ensemble if the weights are in models/.
    Dev (laptop): MediaPipe FaceMesh passive depth + blink.
    Nothing available: returns (True, 1.0) so dev_mode can still run (fail-open).
    """

    def __init__(self, cfg, models_dir):
        self.kind = "none"
        self.backend = None
        self.error = None
        try:
            specs = cfg.get("liveness.minifasnet_models") or []
            self.backend = MiniFASNet(
                models_dir, [(s, f) for s, f in specs],
                live_thr=cfg.get("liveness.live_score_thr", 0.90),
            )
            self.kind = "minifasnet"
            return
        except Exception as e:  # weights missing on laptop -> try passive
            self.error = str(e)
        try:
            self.backend = PassiveLiveness(
                models_dir,
                depth_thr=cfg.get("liveness.passive_depth_thr", 0.10),
                ear_thr=cfg.get("liveness.blink_ear_thr", 0.21),
            )
            self.kind = "passive"
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.warning("no liveness backend available: %s", e)

    def check(self, frame, det) -> tuple[bool, float]:
        if self.backend is None:
            return True, 1.0     # fail-open (dev only)
        return self.backend.is_live(frame, det)


def _softmax(v, np):
    e = np.exp(v - np.max(v))
    return e / e.sum()


def _ear(pts, idx):
    import math
    p = [pts[i] for i in idx]
    def d(a, b):
        return math.dist(a, b)
    horiz = d(p[0], p[3]) or 1e-6
    return (d(p[1], p[5]) + d(p[2], p[4])) / (2.0 * horiz)
