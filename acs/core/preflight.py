"""Startup safety checks — surface unsafe-for-production config LOUDLY.

A door controller that ships with dev defaults (fail-open liveness, default
password, placeholder session secret, plaintext biometrics) is a security
hole. These warnings make the operator aware before the door goes live.
"""
from __future__ import annotations


def production_warnings(cfg, cipher_enabled: bool) -> list[str]:
    """Return human-readable warnings for unsafe production settings.

    `cipher_enabled` = whether the encryption backend actually initialized."""
    w: list[str] = []
    dev = bool(cfg.get("dev_mode", False))
    if dev:
        w.append("dev_mode=true: liveness fails OPEN if the backend is missing — "
                 "set dev_mode:false on the Pi before going live.")
    if cfg.get("web.default_password", "admin") == "admin":
        w.append("web.default_password is still 'admin' — change it from the dashboard.")
    sec = (cfg.get("web.session_secret", "") or "").strip()
    if sec in ("", "change-me", "change-me-to-a-long-random-string") or len(sec) < 32:
        w.append("web.session_secret is default/weak — a random secret will be "
                 "generated; set a strong one in config to silence this.")
    if cfg.get("web.host", "127.0.0.1") == "0.0.0.0":
        w.append("web.host=0.0.0.0 exposes the dashboard on the LAN — ensure the "
                 "password and session_secret are strong.")
    if cfg.get("intruder.encrypt_images", True) and not cipher_enabled:
        w.append("intruder.encrypt_images=true but the encryption backend is "
                 "unavailable — intruder images would be stored PLAINTEXT.")
    if not dev and (not cfg.get("liveness.enabled", True)
                    or not cfg.get("liveness.require_liveness", True)):
        w.append("production (dev_mode:false) with liveness disabled — the "
                 "anti-spoof gate is OFF.")
    return w
