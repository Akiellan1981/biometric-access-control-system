"""Dashboard self-check: report each subsystem's health so an operator can verify
the system is working from the browser, without reading logs. Side-effect-free
(filesystem + imports + DB reads) — the live camera test is a separate route."""
from __future__ import annotations

from pathlib import Path


def _row(name, status, detail=""):
    return {"name": name, "status": status, "detail": detail}


def _imp_version(mod: str):
    try:
        m = __import__(mod)
        return getattr(m, "__version__", "ok")
    except Exception:  # noqa: BLE001
        return None


def system_status(cfg, db, cipher_enabled: bool, lang: str = "en") -> list[dict]:
    """List of {name, status: ok|warn|fail, detail} checks for the status page."""
    rows: list[dict] = []

    # Database + gallery
    try:
        n_people = len(db.list_people())
        db.recent_events(1)
        rows.append(_row("Database", "ok", "reachable"))
        rows.append(_row("Enrolled people", "ok" if n_people else "warn",
                         f"{n_people} enrolled" if n_people
                         else "none enrolled — nobody can be granted yet"))
    except Exception as e:  # noqa: BLE001
        rows.append(_row("Database", "fail", str(e)))

    # Encryption of biometric templates / photos
    rows.append(_row("Template encryption", "ok" if cipher_enabled else "warn",
                     "enabled" if cipher_enabled
                     else "DISABLED — biometrics would be stored in plaintext"))

    # ML models on disk
    models = Path(cfg.path("paths.models"))
    for label, key in (("Face-detect model (YuNet)", "face.detect_model"),
                       ("Face-recognise model (SFace)", "face.recog_model")):
        fn = cfg.get(key)
        ok = bool(fn) and (models / fn).exists()
        rows.append(_row(label, "ok" if ok else "fail", fn or "(unset)"))
    fl = models / "face_landmarker.task"
    rows.append(_row("Liveness model (FaceLandmarker)", "ok" if fl.exists() else "fail",
                     "present" if fl.exists()
                     else "missing — on the Pi liveness fails CLOSED (everyone denied)"))

    # Python libraries
    for label, mod in (("OpenCV", "cv2"), ("MediaPipe", "mediapipe"),
                       ("ONNX Runtime", "onnxruntime"), ("Cryptography", "cryptography")):
        v = _imp_version(mod)
        rows.append(_row(label, "ok" if v else "fail", str(v) if v else "not importable"))

    # Voice clips for the active language
    if cfg.get("voice.enabled", True):
        base = Path(cfg.path("paths.voice"))
        clips = cfg.get("voice.clips", {}) or {}
        present = sum(1 for f in clips.values()
                      if (base / lang / f).exists() or (base / f).exists())
        total = len(clips)
        rows.append(_row(f"Voice clips [{lang}]",
                         "ok" if total and present == total else "warn",
                         f"{present}/{total} present"
                         + ("" if present == total else " — run scripts/render_voice.py")))
    else:
        rows.append(_row("Voice", "warn", "disabled"))

    # Fingerprint driver
    drv = cfg.get("fingerprint.driver", "mock")
    rows.append(_row("Fingerprint driver", "ok" if drv != "mock" else "warn",
                     drv if drv != "mock" else "mock (no real sensor wired)"))

    return rows
