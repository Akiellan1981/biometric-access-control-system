"""Status page self-check: each subsystem reports ok/warn/fail correctly."""
from pathlib import Path

from acs.config import Config
from acs.core.selfcheck import system_status
from acs.storage.db import DB


def _cfg(tmp_path):
    data = {"paths": {"models": "models", "voice": "voice"},
            "face": {"detect_model": "yunet.onnx", "recog_model": "sface.onnx"},
            "voice": {"enabled": True, "clips": {"welcome": "welcome.wav"}},
            "fingerprint": {"driver": "mock"}}
    return Config(data, Path(tmp_path))


def _status_map(tmp_path, cipher_enabled=True):
    db = DB(tmp_path / "d.db"); db.init_schema()
    rows = system_status(_cfg(tmp_path), db, cipher_enabled, lang="en")
    return {r["name"]: r for r in rows}


def test_missing_models_fail(tmp_path):
    m = _status_map(tmp_path)
    assert m["Face-detect model (YuNet)"]["status"] == "fail"     # no file on disk
    assert m["Liveness model (FaceLandmarker)"]["status"] == "fail"
    assert m["Database"]["status"] == "ok"


def test_no_people_warns(tmp_path):
    m = _status_map(tmp_path)
    assert m["Enrolled people"]["status"] == "warn"


def test_encryption_warn_when_disabled(tmp_path):
    m = _status_map(tmp_path, cipher_enabled=False)
    assert m["Template encryption"]["status"] == "warn"


def test_present_models_ok(tmp_path):
    cfg = _cfg(tmp_path)
    models = Path(cfg.path("paths.models")); models.mkdir(parents=True)
    (models / "yunet.onnx").write_bytes(b"x")
    (models / "sface.onnx").write_bytes(b"x")
    (models / "face_landmarker.task").write_bytes(b"x")
    db = DB(tmp_path / "d.db"); db.init_schema(); db.add_person("Asha")
    m = {r["name"]: r for r in system_status(cfg, db, True, "en")}
    assert m["Face-detect model (YuNet)"]["status"] == "ok"
    assert m["Liveness model (FaceLandmarker)"]["status"] == "ok"
    assert m["Enrolled people"]["status"] == "ok"
