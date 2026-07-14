"""Password hashing (PBKDF2, stdlib) and signed session cookies (HMAC)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from pathlib import Path

_ITER = 200_000

_WEAK_SECRETS = {"", "change-me", "change-me-to-a-long-random-string"}


def load_or_create_secret(key_file, configured: str | None) -> str:
    """Return a strong HMAC secret. If `configured` is a known placeholder / too
    short (<32 chars), read or generate a persistent random secret from key_file
    instead, so the dashboard is never signed with the repo's default secret
    (which an attacker could use to forge an admin session cookie)."""
    import os
    cfgd = (configured or "").strip()
    if cfgd not in _WEAK_SECRETS and len(cfgd) >= 32:
        return cfgd
    p = Path(key_file)
    if p.exists():
        existing = p.read_text().strip()
        if existing:
            return existing
    secret = base64.urlsafe_b64encode(os.urandom(48)).decode()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(secret)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return secret


def hash_password(password: str) -> str:
    import os
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return "pbkdf2$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, b64salt, b64dk = stored.split("$")
        salt = base64.b64decode(b64salt)
        dk = base64.b64decode(b64dk)
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
        return hmac.compare_digest(test, dk)
    except Exception:
        return False


def make_token(username: str, secret: str, hours: int) -> str:
    exp = int(time.time()) + hours * 3600
    msg = f"{username}|{exp}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}|{sig}".encode()).decode()


def read_token(token: str, secret: str) -> str | None:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, exp, sig = raw.split("|")
        good = hmac.new(secret.encode(), f"{username}|{exp}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig) or int(exp) < time.time():
            return None
        return username
    except Exception:
        return None
