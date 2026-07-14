"""Intruder capture: encrypted dashboard copy + protected memory-card archive.
The archive only auto-deletes at retention; there is no manual archive delete."""
import os
import time
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from acs.config import Config  # noqa: E402
from acs.core.intruder import IntruderCapture  # noqa: E402
from acs.storage.crypto import TemplateCipher  # noqa: E402


def _cfg(tmp_path):
    data = {"paths": {"unauthorized": "unauth", "archive": "archive", "key_file": "k.key"},
            "intruder": {"enabled": True, "dedupe_seconds": 0, "encrypt_images": True,
                         "archive_copy": True, "retention_days": 31}}
    return Config(data, Path(tmp_path))


def _frame():
    return np.zeros((40, 40, 3), dtype="uint8")


def test_capture_writes_dashboard_and_archive(tmp_path):
    cfg = _cfg(tmp_path)
    cipher = TemplateCipher(cfg.path("paths.key_file"))
    cap = IntruderCapture(cfg, cipher=cipher)
    path = cap.capture(_frame(), "spoof")
    assert path and path.endswith(".jpg.enc")
    name = Path(path).name
    assert (Path(cfg.path("paths.unauthorized")) / name).exists()   # dashboard copy
    assert (Path(cfg.path("paths.archive")) / name).exists()        # protected archive copy
    assert cipher.decrypt((Path(cfg.path("paths.archive")) / name).read_bytes())[:2] == b"\xff\xd8"


def test_purge_removes_old_from_both(tmp_path):
    cfg = _cfg(tmp_path)
    cipher = TemplateCipher(cfg.path("paths.key_file"))
    cap = IntruderCapture(cfg, cipher=cipher)
    old = time.time() - 40 * 86400
    for d in (cap.dir, cap.archive_dir):
        f = d / "20200101_000000_spoof.jpg.enc"
        f.write_bytes(b"x")
        os.utime(f, (old, old))
    cap.purge_old()
    assert not (cap.dir / "20200101_000000_spoof.jpg.enc").exists()
    assert not (cap.archive_dir / "20200101_000000_spoof.jpg.enc").exists()


def test_recent_archive_kept(tmp_path):
    cfg = _cfg(tmp_path)
    cap = IntruderCapture(cfg, cipher=TemplateCipher(cfg.path("paths.key_file")))
    f = cap.archive_dir / "recent_spoof.jpg.enc"
    f.write_bytes(b"x")                       # fresh mtime
    cap.purge_old()
    assert f.exists()                         # within 31 days -> kept
