"""Multilingual voice (en/ta/hi): clips resolve from the active language folder,
the language switches live via the DB setting (seen by other Voice instances /
processes), and a missing clip falls back to English."""
from pathlib import Path

from acs.config import Config
from acs.core.voice import Voice
from acs.storage.db import DB


def _setup(tmp_path):
    base = tmp_path / "voice"
    for lang in ("en", "ta", "hi"):
        (base / lang).mkdir(parents=True)
        (base / lang / "blink.wav").write_bytes(b"RIFF")        # all langs have blink
    (base / "en" / "turn_left.wav").write_bytes(b"RIFF")        # only EN has turn_left
    data = {"paths": {"voice": "voice"},
            "voice": {"enabled": True, "language": "en",
                      "clips": {"blink": "blink.wav", "turn_left": "turn_left.wav"}}}
    cfg = Config(data, Path(tmp_path))
    db = DB(tmp_path / "d.db")
    db.init_schema()
    return cfg, db, base


def test_default_language_en(tmp_path):
    cfg, db, base = _setup(tmp_path)
    v = Voice(cfg, db)
    assert v.language() == "en"
    assert v._resolve("blink") == base / "en" / "blink.wav"


def test_switch_language_reflects_across_instances(tmp_path):
    cfg, db, base = _setup(tmp_path)
    v = Voice(cfg, db)
    assert v.set_language("ta") is True
    assert v.language() == "ta"
    assert v._resolve("blink") == base / "ta" / "blink.wav"
    # a SEPARATE Voice on the same DB (e.g. the door process) sees the switch
    assert Voice(cfg, db).language() == "ta"


def test_fallback_to_english_when_clip_missing(tmp_path):
    cfg, db, base = _setup(tmp_path)
    v = Voice(cfg, db)
    v.set_language("ta")
    assert v._resolve("turn_left") == base / "en" / "turn_left.wav"   # ta missing -> en


def test_unknown_language_rejected(tmp_path):
    cfg, db, _ = _setup(tmp_path)
    v = Voice(cfg, db)
    assert v.set_language("zz") is False
    assert v.language() == "en"
    assert set(v.LANGS) == {"en", "ta", "hi"}
