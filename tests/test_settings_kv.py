"""Guards the runtime settings store that backs live voice-language switching:
the dashboard writes it, the door pipeline reads it, via this one DB file."""
from acs.storage.db import DB


def test_setting_roundtrip_and_default(tmp_path):
    db = DB(tmp_path / "d.db")
    db.init_schema()
    assert db.get_setting("voice_lang", "en") == "en"   # default when unset
    db.set_setting("voice_lang", "ta")
    assert db.get_setting("voice_lang") == "ta"
    db.set_setting("voice_lang", "hi")                   # overwrite
    assert db.get_setting("voice_lang") == "hi"
