"""Insert sample people, events, and intruder images so the dashboard isn't empty.

    python scripts/seed_demo.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acs.config import Config
from acs.storage.db import DB


def _placeholder_image(path: Path, label: str):
    try:
        import cv2
        import numpy as np
        img = np.full((240, 240, 3), 70, dtype="uint8")
        cv2.putText(img, label, (20, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)
        cv2.imwrite(str(path), img)
        return True
    except Exception:
        return False


def main():
    cfg = Config.load()
    db = DB(cfg.path("paths.db"))
    db.init_schema()

    for name in ["Asha Khan", "Ravi Mehta", "Sara Iyer"]:
        if not any(p["name"] == name for p in db.list_people()):
            db.add_person(name)

    intr_dir = Path(cfg.path("paths.unauthorized"))
    intr_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    samples = [
        ("Asha Khan", "face", "granted", 0.71, None),
        ("Ravi Mehta", "fingerprint", "granted", 0.92, None),
        ("unknown", "face", "denied-spoof", 0.10, "spoof"),
        ("unknown", "face", "denied-unknown", 0.22, "unknown"),
        ("Sara Iyer", "face", "granted", 0.66, None),
    ]
    for i, (name, method, result, score, tag) in enumerate(samples):
        ts = (now - timedelta(minutes=9 * i)).strftime("%Y-%m-%d %H:%M:%S")
        image_path = None
        if tag:
            p = intr_dir / f"demo_{i}_{tag}.jpg"
            if _placeholder_image(p, tag):
                image_path = str(p)
        db.log_event(None, name, method, result, score, image_path, ts=ts)

    print("seeded demo data ->", cfg.path("paths.db"))


if __name__ == "__main__":
    main()
