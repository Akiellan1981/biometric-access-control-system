"""Face recognition with SFace (OpenCV): embeddings + cosine matching. FR-1.2."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class FaceRecognizer:
    def __init__(self, model_path: str | Path, cosine_thr: float = 0.363):
        import cv2
        import numpy as np
        self._cv2 = cv2
        self._np = np
        self._rec = cv2.FaceRecognizerSF.create(str(model_path), "")
        self.cosine_thr = cosine_thr

    def embed(self, frame, detection_raw):
        """Align+crop the face then return a normalized 128-D float32 embedding."""
        aligned = self._rec.alignCrop(frame, detection_raw)
        feat = self._rec.feature(aligned).flatten().astype("float32")
        n = self._np.linalg.norm(feat)
        return feat / n if n > 0 else feat

    def match(self, emb, gallery, margin: float = 0.0):
        """gallery: list of (person_id, name, embedding ndarray).
        Returns (person_id|None, name|None, best_score).

        `margin`: require the best person to beat the best DIFFERENT person by at
        least this cosine gap, else reject as ambiguous (avoids confusing
        look-alikes) — costs at most one extra cheap pass and only when matched."""
        np = self._np
        best_id: Optional[int] = None
        best_name: Optional[str] = None
        best = -1.0
        for pid, name, g in gallery:
            score = float(np.dot(emb, g))   # both normalized -> cosine similarity
            if score > best:
                best, best_id, best_name = score, pid, name
        if best < self.cosine_thr:
            return None, None, best
        if margin > 0.0:
            other = -1.0
            has_other = False
            for pid, _name, g in gallery:
                if pid == best_id:
                    continue
                has_other = True
                other = max(other, float(np.dot(emb, g)))
            if has_other and (best - other) < margin:
                return None, None, best   # too close to another person -> ambiguous
        return best_id, best_name, best

    def to_blob(self, emb) -> bytes:
        return self._np.asarray(emb, dtype="float32").tobytes()

    def from_blob(self, blob: bytes):
        return self._np.frombuffer(blob, dtype="float32")
