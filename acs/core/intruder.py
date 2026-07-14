"""Intruder evidence capture (spec FR-5): save denied-face photos, tag, dedupe.

Two copies are written:
  - the DASHBOARD copy (paths.unauthorized) — an admin can delete it (with the
    admin password) individually, in bulk, or the whole directory;
  - the ARCHIVE copy (paths.archive) on the memory card — a tamper-resistant
    forensic copy with NO manual-delete path; it only auto-deletes at the
    retention limit (31 days). So evidence survives a dashboard wipe for a month.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class IntruderCapture:
    def __init__(self, cfg, cipher=None):
        self.enabled = bool(cfg.get("intruder.enabled", True))
        self.dir = Path(cfg.path("paths.unauthorized"))
        self.dedupe_s = float(cfg.get("intruder.dedupe_seconds", 20))
        self.retention_days = int(cfg.get("intruder.retention_days", 31))
        self.dir.mkdir(parents=True, exist_ok=True)
        self._last_save = 0.0
        self.cipher = cipher
        self.encrypt = (bool(cfg.get("intruder.encrypt_images", True))
                        and cipher is not None and getattr(cipher, "enabled", False))
        # Protected memory-card archive (no manual delete; auto-purge only).
        self.archive_dir = None
        if cfg.get("intruder.archive_copy", True) and cfg.path("paths.archive"):
            self.archive_dir = Path(cfg.path("paths.archive"))
            self.archive_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, frame, tag: str) -> str | None:
        """tag: 'unknown' | 'spoof'. Returns the dashboard-copy path or None.
        Also writes the same bytes to the protected archive."""
        if not self.enabled or frame is None:
            return None
        now = time.time()
        if now - self._last_save < self.dedupe_s:   # FR-5.3 avoid disk flooding
            return None
        try:
            import cv2
        except Exception:
            log.warning("cv2 unavailable; cannot save intruder image")
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        if not ok:
            return None
        data = buf.tobytes()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.encrypt:
            data = self.cipher.encrypt(data)
            fname = f"{stamp}_{tag}.jpg.enc"
        else:
            fname = f"{stamp}_{tag}.jpg"
        path = self.dir / fname
        try:
            path.write_bytes(data)
        except OSError as e:
            log.warning("could not save intruder image: %s", e)
            return None
        # protected archive copy (best-effort; never blocks the dashboard copy)
        if self.archive_dir is not None:
            try:
                (self.archive_dir / fname).write_bytes(data)
            except OSError as e:
                log.warning("could not write archive copy: %s", e)
        self._last_save = now
        return str(path)

    def _purge_dir(self, d: Path, cutoff: float):
        for pattern in ("*.jpg", "*.jpg.enc"):
            for f in d.glob(pattern):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except OSError:
                    pass

    def purge_old(self):
        """Auto-delete images older than the retention limit — in BOTH the dashboard
        dir and the protected archive. This is the ONLY thing that removes archive
        files (there is no manual archive delete)."""
        if self.retention_days <= 0:
            return
        cutoff = time.time() - self.retention_days * 86400
        self._purge_dir(self.dir, cutoff)
        if self.archive_dir is not None:
            self._purge_dir(self.archive_dir, cutoff)
