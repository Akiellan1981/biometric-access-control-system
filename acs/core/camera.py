"""Camera abstraction: picamera2 on the Pi, OpenCV webcam for dev, mock fallback."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class _MockCamera:
    """Yields a synthetic gray frame so the pipeline loop can run without a camera."""
    def __init__(self, width=640, height=480):
        self.w, self.h = width, height

    def read(self):
        try:
            import numpy as np
        except Exception:
            return None
        return np.full((self.h, self.w, 3), 60, dtype="uint8")

    def release(self):
        pass


class _OpenCVCamera:
    def __init__(self, index=0, width=640, height=480):
        import platform
        import cv2
        self._cv2 = cv2
        # DirectShow opens far faster/more reliably on Windows laptops
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, backend)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open OpenCV camera index {index}")

    def read(self):
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self):
        self._cap.release()


class _PiCamera:
    def __init__(self, width=640, height=480):
        from picamera2 import Picamera2
        import cv2
        self._cv2 = cv2
        self._cam = Picamera2()
        cfg = self._cam.create_preview_configuration(
            main={"size": (width, height), "format": "RGB888"}
        )
        self._cam.configure(cfg)
        self._cam.start()

    def read(self):
        rgb = self._cam.capture_array()
        return self._cv2.cvtColor(rgb, self._cv2.COLOR_RGB2BGR)

    def release(self):
        self._cam.stop()


def open_camera(cfg, source=None):
    """Build a camera; returns an object with .read() -> BGR frame | None.
    `source` (auto|picamera2|opencv|mock) overrides config — used by the dashboard
    camera toggle (PC webcam vs Raspberry Pi camera)."""
    source = (source or cfg.get("camera.source") or "auto").lower()
    w = cfg.get("camera.width", 640)
    h = cfg.get("camera.height", 480)
    idx = cfg.get("camera.index", 0)

    order = {
        "picamera2": ["pi"],
        "opencv": ["cv"],
        "mock": ["mock"],
        "auto": ["pi", "cv", "mock"],
    }.get(source, ["mock"])

    for kind in order:
        try:
            if kind == "pi":
                return _PiCamera(w, h)
            if kind == "cv":
                return _OpenCVCamera(idx, w, h)
            if kind == "mock":
                return _MockCamera(w, h)
        except Exception as e:  # noqa: BLE001
            log.warning("camera '%s' unavailable: %s", kind, e)
    log.error("no camera available; using mock")
    return _MockCamera(w, h)
