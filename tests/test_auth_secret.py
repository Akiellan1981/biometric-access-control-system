"""Guards the session-secret fix (Mythos v2 storage F-01): the dashboard must
never be signed with the repo's default secret, or an attacker could forge an
admin cookie. A weak/placeholder secret auto-generates a persistent random one."""
from acs.web.auth import load_or_create_secret, make_token, read_token


def test_strong_secret_used_asis(tmp_path):
    strong = "x" * 40
    out = load_or_create_secret(tmp_path / "s.key", strong)
    assert out == strong
    assert not (tmp_path / "s.key").exists()   # no file created when config is strong


def test_weak_secret_autogenerates_and_persists(tmp_path):
    kf = tmp_path / "s.key"
    s1 = load_or_create_secret(kf, "change-me-to-a-long-random-string")
    assert s1 != "change-me-to-a-long-random-string"
    assert len(s1) >= 32
    assert kf.exists()
    s2 = load_or_create_secret(kf, None)       # second call reuses the same secret
    assert s2 == s1


def test_forged_default_token_rejected(tmp_path):
    real = load_or_create_secret(tmp_path / "s.key", None)
    forged = make_token("admin", "change-me-to-a-long-random-string", 8)
    assert read_token(forged, real) is None              # forgery rejected
    assert read_token(make_token("admin", real, 8), real) == "admin"  # real round-trips
