"""Device entry point (spec FR-MODE-2, Run mode).

Starts the face + fingerprint producer threads and the single decision/logging
consumer. Add --web to also serve the dashboard in a background thread.

    python run.py            # device pipeline only
    python run.py --web      # pipeline + LAN dashboard
"""
from __future__ import annotations

# Silence MediaPipe native C++ log spam before anything initializes it.
from acs.core.quiet import silence_native_stderr  # noqa: E402

silence_native_stderr()

import argparse  # noqa: E402
import logging  # noqa: E402
import queue  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from acs.config import Config
from acs.core.decision import DecisionEngine
from acs.core.intruder import IntruderCapture
from acs.core.relay import Relay
from acs.core.voice import Voice
from acs.storage.crypto import TemplateCipher
from acs.storage.db import DB
from acs.web.auth import hash_password

log = logging.getLogger(__name__)


def ensure_admin(db: DB, cfg: Config):
    user = cfg.get("web.admin_user", "admin")
    if not db.get_user(user):
        db.upsert_user(user, hash_password(cfg.get("web.default_password", "admin")))
        log.warning("seeded admin '%s' with default password — change it!", user)


def start_web(cfg: Config):
    import uvicorn
    from acs.web.app import app
    cfg_uv = uvicorn.Config(app, host=cfg.get("web.host", "127.0.0.1"),
                            port=cfg.get("web.port", 8000), log_level="info")
    threading.Thread(target=uvicorn.Server(cfg_uv).run, daemon=True).start()
    log.info("dashboard on http://%s:%s", cfg.get("web.host"), cfg.get("web.port"))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", action="store_true", help="also serve the dashboard")
    args = ap.parse_args()

    cfg = Config.load()
    db = DB(cfg.path("paths.db"))
    db.init_schema()
    ensure_admin(db, cfg)

    cipher = TemplateCipher(cfg.path("paths.key_file"))
    voice = Voice(cfg, db)              # db-backed language (live-switchable from dashboard)
    relay = Relay(cfg)
    intruder = IntruderCapture(cfg, cipher=cipher)
    decision = DecisionEngine(db, cfg, voice=voice, relay=relay, intruder=intruder)
    retention = int(cfg.get("intruder.retention_days", 30))

    def maintenance():
        """Enforce the retention window: drop event rows older than retention and
        unlink their captured images; also purge stray intruder files by age."""
        for img in db.purge_events(retention):
            try:
                (Path(cfg.path("paths.unauthorized")) / Path(img).name).unlink()
            except OSError:
                pass
        intruder.purge_old()

    maintenance()

    from acs.core.preflight import production_warnings
    for _w in production_warnings(cfg, getattr(cipher, "enabled", False)):
        log.warning("PREFLIGHT: %s", _w)

    q: "queue.Queue" = queue.Queue()
    stop = threading.Event()

    def _maintenance_loop():           # re-run retention hourly (door runs for weeks)
        while not stop.is_set():
            if stop.wait(3600):
                break
            maintenance()
    threading.Thread(target=_maintenance_loop, daemon=True).start()

    from acs.core.fingerprint import create_sensor
    from acs.pipeline.face_thread import FaceThread
    from acs.pipeline.finger_thread import FingerThread

    face = FaceThread(cfg, db, cipher, q, stop, voice=voice)   # voice-guided challenge
    finger = FingerThread(cfg, db, create_sensor(cfg), q, stop)
    face.start()
    finger.start()
    if args.web:
        start_web(cfg)

    log.info("Run mode active (dev_mode=%s). Ctrl+C to stop.", cfg.get("dev_mode"))
    try:
        while True:
            try:
                cand = q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                decision.handle(cand)
            except Exception as e:  # noqa: BLE001 - a DB/handler hiccup must not crash the door
                log.exception("decision error (continuing): %s", e)
    except KeyboardInterrupt:
        log.info("stopping...")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
