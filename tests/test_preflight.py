"""Guards the production preflight warnings (Mythos v2 C1/C2/M1/F-02): unsafe
deploy config must be surfaced loudly rather than silently shipping a fail-open
door."""
from pathlib import Path

from acs.config import Config
from acs.core.preflight import production_warnings


def test_unsafe_config_warns(tmp_path):
    data = {
        "dev_mode": True,
        "web": {"default_password": "admin",
                "session_secret": "change-me-to-a-long-random-string",
                "host": "0.0.0.0"},
        "intruder": {"encrypt_images": True},
    }
    cfg = Config(data, Path(tmp_path))
    w = production_warnings(cfg, cipher_enabled=False)
    assert len(w) >= 5
    assert any("PLAINTEXT" in s for s in w)
    assert any("dev_mode" in s for s in w)


def test_safe_config_no_warns(tmp_path):
    data = {
        "dev_mode": False,
        "web": {"default_password": "s3cret!!", "session_secret": "x" * 40,
                "host": "127.0.0.1"},
        "intruder": {"encrypt_images": True},
        "liveness": {"enabled": True, "require_liveness": True},
    }
    cfg = Config(data, Path(tmp_path))
    assert production_warnings(cfg, cipher_enabled=True) == []
