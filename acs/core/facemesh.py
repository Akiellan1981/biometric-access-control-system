"""MediaPipe Tasks FaceLandmarker wrapper.

Newer MediaPipe wheels (0.10.x on Windows) ship ONLY the Tasks API — the legacy
``mediapipe.solutions.face_mesh`` module is gone. This wrapper exposes the dense
478-point face mesh (normalized x, y, z) through the Tasks ``FaceLandmarker`` so
liveness and the enrollment mesh keep working on a single, available API.

Needs the model file ``models/face_landmarker.task``:
    python scripts/download_models.py
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

MODEL_FILE = "face_landmarker.task"


class FaceLandmarks:
    """Thin wrapper around Tasks FaceLandmarker.

    mode='video' uses RunningMode.VIDEO, which TRACKS the face across frames instead
    of re-detecting each frame — far more consistent/stable (and faster) for the
    continuous liveness monitor. mode='image' is single-shot (fallbacks/overlay)."""

    def __init__(self, models_dir, max_faces: int = 1, min_conf: float = 0.4, mode: str = "image"):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._video = (mode == "video")
        self._ts = 0
        path = Path(models_dir) / MODEL_FILE
        if not path.exists():
            raise FileNotFoundError(
                f"face mesh model missing: {path} — run: python scripts/download_models.py")
        kwargs = dict(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO if self._video else vision.RunningMode.IMAGE,
            num_faces=max_faces,
            min_face_detection_confidence=min_conf,
            output_face_blendshapes=True,   # model-grade eyeBlink/gaze/jaw — ~free, graph already built
        )
        if self._video:
            # Tracking confidences keep the mesh locked on between detections.
            kwargs["min_face_presence_confidence"] = 0.5
            kwargs["min_tracking_confidence"] = 0.5
        opts = vision.FaceLandmarkerOptions(**kwargs)
        self._lm = vision.FaceLandmarker.create_from_options(opts)

    def _run(self, frame_bgr):
        import cv2
        import time
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        if self._video:
            self._ts = max(self._ts + 1, int(time.monotonic() * 1000))  # strictly increasing
            res = self._lm.detect_for_video(img, self._ts)
        else:
            res = self._lm.detect(img)
        if not res.face_landmarks:
            return None, None
        pts = [(p.x, p.y, p.z) for p in res.face_landmarks[0]]
        blend = None
        if getattr(res, "face_blendshapes", None):
            blend = {c.category_name: c.score for c in res.face_blendshapes[0]}
        return pts, blend

    def detect(self, frame_bgr):
        """Return [(x, y, z), ...] normalized landmarks for the first face, or None."""
        return self._run(frame_bgr)[0]

    def detect_full(self, frame_bgr):
        """Return (landmarks, blendshapes_dict) — blendshapes carry eyeBlink/gaze/jaw."""
        return self._run(frame_bgr)
