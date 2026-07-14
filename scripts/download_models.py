"""Download the pre-trained OpenCV models (YuNet + SFace) into models/.

MiniFASNet liveness weights are NOT downloaded here — get them from the
Silent-Face-Anti-Spoofing repo and convert with export_minifasnet_onnx.py.

    python scripts/download_models.py
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

MODELS = Path(__file__).resolve().parent.parent / "models"

FILES = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
    # MediaPipe Tasks FaceLandmarker (478-pt mesh) — used for passive liveness
    # (rejects flat photos/screens) and the enrollment mesh overlay.
    "face_landmarker.task":
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
}


def main():
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        dest = MODELS / name
        if dest.exists():
            print(f"[skip] {name} already present")
            continue
        print(f"[get ] {name} ...")
        urllib.request.urlretrieve(url, dest)
        print(f"[done] {dest} ({dest.stat().st_size // 1024} KB)")
    print("\nNext: place MiniFASNet ONNX files in models/ (see export_minifasnet_onnx.py).")


if __name__ == "__main__":
    main()
