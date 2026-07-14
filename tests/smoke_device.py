"""Smoke-test the device pipeline in dev/mock mode (no camera/sensor/ML deps)."""
import queue
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# import every module to catch syntax/import errors
import acs.core.camera, acs.core.relay, acs.core.voice, acs.core.intruder      # noqa
import acs.core.face_detect, acs.core.face_recognize, acs.core.liveness        # noqa
import acs.enroll, run                                                         # noqa
print("all modules import OK")

from acs.config import Config
from acs.core.decision import DecisionEngine
from acs.core.fingerprint import create_sensor
from acs.core.relay import Relay
from acs.core.voice import Voice
from acs.core.intruder import IntruderCapture
from acs.storage.crypto import TemplateCipher
from acs.storage.db import DB
from acs.pipeline.face_thread import FaceThread
from acs.pipeline.finger_thread import FingerThread

cfg = Config.load()
db = DB(cfg.path("paths.db")); db.init_schema()
cipher = TemplateCipher(cfg.path("paths.key_file"))
q = queue.Queue(); stop = threading.Event()

face = FaceThread(cfg, db, cipher, q, stop)
print("FaceThread enabled (recognition available)?", face.enabled, "- expected False without cv2/models")

sensor = create_sensor(cfg)
print("fingerprint sensor:", type(sensor).__name__)
finger = FingerThread(cfg, db, sensor, q, stop)

# enroll a person + finger slot, then simulate a touch -> finger thread -> decision
pid = db.add_person("Smoke Tester")
slot = sensor.enroll(); db.add_finger_template(pid, slot)
decision = DecisionEngine(db, cfg, voice=Voice(cfg), relay=Relay(cfg), intruder=IntruderCapture(cfg))

finger.start()
sensor.simulate_touch(slot, 95)
cand = q.get(timeout=3)
res = decision.handle(cand)
print("finger candidate ->", res)
assert res.value == "granted"
stop.set()
print("\nDEVICE SMOKE OK")
