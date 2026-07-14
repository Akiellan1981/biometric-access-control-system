"""Face detection with YuNet (OpenCV). Spec FR-1.1."""
from __future__ import annotations

from pathlib import Path

from acs.types import Detection


class FaceDetector:
    def __init__(self, model_path: str | Path, score_thr=0.8, nms_thr=0.3, top_k=50):
        import cv2
        self._cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(
            str(model_path), "", (320, 320), score_thr, nms_thr, top_k
        )

    def detect(self, frame) -> list[Detection]:
        h, w = frame.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(frame)
        out: list[Detection] = []
        if faces is None:
            return out
        for f in faces:
            x, y, bw, bh = (int(v) for v in f[:4])
            out.append(Detection(
                x=x, y=y, w=bw, h=bh,
                score=float(f[-1]),
                landmarks=f[4:14].reshape(5, 2),
                raw=f,                       # SFace.alignCrop needs this row
            ))
        return out

    @staticmethod
    def largest(dets: list[Detection], min_width: int) -> Detection | None:
        """Act on the closest/largest face only, ignoring small ones (FR-1.4)."""
        big = [d for d in dets if d.w >= min_width]
        return max(big, key=lambda d: d.w * d.h) if big else None

    @staticmethod
    def count_qualifying(faces, min_w) -> int:
        """How many detected faces meet the minimum width (ignore tiny/background).
        Used to refuse a decision when >1 close face is present, so liveness can't
        be bound to the wrong identity."""
        return sum(1 for f in faces if getattr(f, "w", 0) >= min_w)

    @staticmethod
    def distance_hint(face_w, frame_w, near_max=0.6, far_min=0.25):
        """Voice-prompt key for framing during enrollment: 'stand_back' if the face
        fills too much of the frame, 'come_closer' if it's too small, else None
        (full face visible at a good distance ~0.5 m)."""
        if not frame_w:
            return None
        frac = face_w / frame_w
        if frac > near_max:
            return "stand_back"
        if frac < far_min:
            return "come_closer"
        return None
