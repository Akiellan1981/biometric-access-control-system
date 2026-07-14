"""Register mode (spec FR-MODE-1): enroll face + fingerprint into one record.

Usage (on the device, person in front of the camera):
    python -m acs.enroll --name "Asha Khan" --samples 6
"""
from __future__ import annotations

import argparse
import logging
import time

from acs.config import Config
from acs.storage.crypto import TemplateCipher
from acs.storage.db import DB

log = logging.getLogger(__name__)


def enroll_face(cfg, db, cipher, person_id: int, samples: int = 6) -> int:
    """Capture N good face samples and store their embeddings. Returns count stored."""
    from acs.core.camera import open_camera
    from acs.core.face_detect import FaceDetector
    from acs.core.face_recognize import FaceRecognizer

    models = cfg.path("paths.models")
    cam = open_camera(cfg)
    det = FaceDetector(models / cfg.get("face.detect_model"),
                       score_thr=cfg.get("face.detect_score_thr", 0.8))
    rec = FaceRecognizer(models / cfg.get("face.recog_model"))
    min_w = cfg.get("face.min_face_width_px", 80)

    stored = 0
    while stored < samples:
        frame = cam.read()
        if frame is None:
            time.sleep(0.05)
            continue
        face = FaceDetector.largest(det.detect(frame), min_w)
        if face is None:
            continue
        emb = rec.embed(frame, face.raw)
        db.add_face_template(person_id, cipher.encrypt(rec.to_blob(emb)))
        stored += 1
        log.info("captured face sample %d/%d", stored, samples)
        time.sleep(0.4)
    cam.release()
    return stored


def enroll_finger(cfg, db, person_id: int) -> int | None:
    """Enroll a fingerprint into the same record. Returns slot or None."""
    from acs.core.fingerprint import create_sensor
    sensor = create_sensor(cfg)
    try:
        log.info("place finger on the sensor...")
        slot = sensor.enroll()
        db.add_finger_template(person_id, slot)
        log.info("fingerprint stored at slot %d", slot)
        return slot
    except Exception as e:  # noqa: BLE001
        log.error("fingerprint enrollment failed: %s", e)
        return None
    finally:
        sensor.close()


def register_person(cfg, name, samples=6, do_face=True, do_finger=True) -> int:
    db = DB(cfg.path("paths.db"))
    db.init_schema()
    cipher = TemplateCipher(cfg.path("paths.key_file"),
                            enabled=cfg.get("storage_encrypt", True) is not False)
    pid = db.add_person(name)
    log.info("created person #%d (%s)", pid, name)
    if do_face:
        enroll_face(cfg, db, cipher, pid, samples)
    if do_finger:
        enroll_finger(cfg, db, pid)
    log.info("registered %s", name)
    return pid


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Register a person (face + fingerprint).")
    ap.add_argument("--name", required=True)
    ap.add_argument("--samples", type=int, default=6)
    ap.add_argument("--no-face", action="store_true")
    ap.add_argument("--no-finger", action="store_true")
    args = ap.parse_args()
    cfg = Config.load()
    register_person(cfg, args.name, args.samples,
                    do_face=not args.no_face, do_finger=not args.no_finger)


if __name__ == "__main__":
    main()
