"""Verify the face engine loads YuNet+SFace and runs, without opening the camera."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from acs.config import Config
from acs.storage.crypto import TemplateCipher
from acs.storage.db import DB
from acs.web.live import FaceEngine


class DummyHub:
    def frame(self):
        return None


cfg = Config.load()
db = DB(cfg.path("paths.db")); db.init_schema()
cipher = TemplateCipher(cfg.path("paths.key_file"))

eng = FaceEngine(cfg, db, cipher, DummyHub())
print("engine available:", eng.available, "| error:", eng.error, "| gallery:", len(eng.gallery))
assert eng.available, "models failed to load"

blank = np.zeros((480, 640, 3), dtype="uint8")
print("recognize(blank):", eng.recognize(blank))   # expect face=False
print("\nFACE ENGINE OK")
