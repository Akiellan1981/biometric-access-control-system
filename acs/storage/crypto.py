"""Encrypt biometric templates at rest (spec §13).

Uses Fernet (AES) with a key kept in a local key file. If `cryptography` is not
installed or encryption is disabled, falls back to pass-through with a warning so
the rest of the system still works during development.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class TemplateCipher:
    def __init__(self, key_file: str | Path, enabled: bool = True):
        self.enabled = enabled
        self._f = None
        if not enabled:
            return
        try:
            from cryptography.fernet import Fernet
        except Exception:
            log.warning("cryptography not installed — templates stored UNENCRYPTED")
            self.enabled = False
            return

        key_file = Path(key_file)
        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_bytes(key)
            try:
                os.chmod(key_file, 0o600)
            except OSError:
                pass
        self._f = Fernet(key)

    def encrypt(self, data: bytes) -> bytes:
        return self._f.encrypt(data) if self.enabled else data

    def decrypt(self, data: bytes) -> bytes:
        return self._f.decrypt(data) if self.enabled else data
