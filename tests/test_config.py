from acs.config import Config


def test_loads_defaults():
    cfg = Config.load()
    assert cfg.get("decision.cooldown_seconds") == 30
    assert cfg.get("face.recognition_cosine_thr") == 0.363
    assert cfg.get("nope.missing", "fallback") == "fallback"


def test_path_resolves_under_root():
    cfg = Config.load()
    p = cfg.path("paths.db")
    assert p.is_absolute()
    assert p.name == "access.db"
