"""Adversarial web-layer checks against the RUNNING FastAPI app (Mythos v2).

Verifies the headline CRITICAL fix end-to-end: a session cookie forged with the
repo's default secret must be REJECTED, and protected routes require auth. These
hit only auth/overview routes (no camera/engine), and mutate no production data.
"""
import pytest

pytest.importorskip("httpx")        # TestClient needs httpx
from fastapi.testclient import TestClient  # noqa: E402

import acs.web.app as appmod  # noqa: E402
from acs.web.auth import make_token  # noqa: E402

client = TestClient(appmod.app)


def test_protected_route_requires_auth():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and "/login" in r.headers.get("location", "")


def test_forged_default_secret_cookie_rejected():
    # Attacker forges an admin cookie using the well-known repo default secret.
    forged = make_token("admin", "change-me-to-a-long-random-string", 8)
    r = client.get("/", cookies={"acs_session": forged}, follow_redirects=False)
    # Because the app auto-generated a real secret, the forgery fails -> login.
    assert r.status_code in (302, 307) and "/login" in r.headers.get("location", "")


def test_garbage_cookie_rejected():
    r = client.get("/", cookies={"acs_session": "not-a-real-token"}, follow_redirects=False)
    assert r.status_code in (302, 307) and "/login" in r.headers.get("location", "")


def test_bad_login_rejected():
    r = client.post("/login", data={"username": "admin", "password": "definitely-wrong"},
                    follow_redirects=False)
    assert r.status_code == 401


def test_login_page_is_public():
    assert client.get("/login").status_code == 200


def test_healthz_public_and_ok():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json().get("ok") is True


def test_spoof_timeout_saved_and_capped_at_30():
    from acs.web.app import SECRET
    cookie = {"acs_session": make_token("admin", SECRET, 8)}
    saved_pw = appmod.db.get_setting("pw_changed", "0")
    saved_ct = appmod.db.get_setting("challenge_timeout_seconds", None)
    try:
        appmod.db.set_setting("pw_changed", "1")
        # within range -> saved as-is
        client.post("/settings/runtime",
                    data={"idle_off": "60", "grant_hold": "5", "spoof_timeout": "15"},
                    cookies=cookie, follow_redirects=False)
        assert appmod.db.get_setting("challenge_timeout_seconds") == "15"
        # over 30 -> clamped to 30
        client.post("/settings/runtime",
                    data={"idle_off": "60", "grant_hold": "5", "spoof_timeout": "99"},
                    cookies=cookie, follow_redirects=False)
        assert appmod.db.get_setting("challenge_timeout_seconds") == "30"
    finally:
        appmod.db.set_setting("pw_changed", saved_pw)
        if saved_ct is not None:
            appmod.db.set_setting("challenge_timeout_seconds", saved_ct)


def test_intruder_delete_requires_admin_password():
    from acs.web.app import SECRET
    cookie = {"acs_session": make_token("admin", SECRET, 8)}
    saved = appmod.db.get_setting("pw_changed", "0")
    try:
        appmod.db.set_setting("pw_changed", "1")
        r = client.post("/intruders/delete", data={"password": "definitely-wrong"},
                        cookies=cookie, follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "Wrong" in r.headers.get("location", "")        # bad password rejected
    finally:
        appmod.db.set_setting("pw_changed", saved)


def test_forced_password_change_redirects_until_done():
    # A validly-signed session is still bounced to /settings until the default
    # password is changed (forced first-login change), then allowed through.
    from acs.web.app import SECRET
    cookie = {"acs_session": make_token("admin", SECRET, 8)}
    saved = appmod.db.get_setting("pw_changed", "0")
    try:
        appmod.db.set_setting("pw_changed", "0")
        r = client.get("/", cookies=cookie, follow_redirects=False)
        assert r.status_code in (302, 307) and "/settings" in r.headers.get("location", "")
        appmod.db.set_setting("pw_changed", "1")
        assert client.get("/", cookies=cookie, follow_redirects=False).status_code == 200
    finally:
        appmod.db.set_setting("pw_changed", saved)
