"""SQLite access layer.

The decision/logging consumer is the only *writer* in the device pipeline
(spec FR-4.5). The web app also reads/writes (people management), so the
connection is opened with check_same_thread=False and writes are guarded by a
lock to keep concurrent access safe.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

SCHEMA = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self):
        with self._lock:
            self._conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            # migrate older DBs: add the per-person live-depth baseline column
            try:
                self._conn.execute("ALTER TABLE people ADD COLUMN live_depth REAL")
            except sqlite3.OperationalError:
                pass  # column already exists
            # runtime key/value settings (e.g. the dashboard-selected voice language),
            # shared across the dashboard and the device pipeline via this one DB file.
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
            self._conn.commit()

    # ---------------- runtime settings (kv) ----------------
    def get_setting(self, key: str, default=None):
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(value)))
            self._conn.commit()

    def close(self):
        self._conn.close()

    # ---------------- people ----------------
    def add_person(self, name: str) -> int:
        with self._lock:
            cur = self._conn.execute("INSERT INTO people(name) VALUES (?)", (name,))
            self._conn.commit()
            return cur.lastrowid

    def get_person(self, person_id: int):
        return self._conn.execute(
            "SELECT * FROM people WHERE person_id=?", (person_id,)
        ).fetchone()

    def get_person_by_name(self, name: str):
        """Case-insensitive lookup so the same person is never registered twice."""
        return self._conn.execute(
            "SELECT * FROM people WHERE name=? COLLATE NOCASE", (name,)
        ).fetchone()

    def get_or_create_person(self, name: str) -> tuple[int, bool]:
        """Return (person_id, created). Reuses an existing person with the same name."""
        row = self.get_person_by_name(name)
        if row:
            return row["person_id"], False
        return self.add_person(name), True

    def set_person_live_depth(self, person_id: int, value: float):
        """Record this person's real-face depth baseline (keeps the running MAX across
        enrollment poses, i.e. the frontal pose) for self-calibrated liveness."""
        with self._lock:
            row = self._conn.execute(
                "SELECT live_depth FROM people WHERE person_id=?", (person_id,)).fetchone()
            prev = row["live_depth"] if row and row["live_depth"] is not None else 0.0
            self._conn.execute("UPDATE people SET live_depth=? WHERE person_id=?",
                               (max(prev, float(value)), person_id))
            self._conn.commit()

    def live_depths(self) -> dict[int, float]:
        """person_id -> stored live-depth baseline (only people that have one)."""
        rows = self._conn.execute(
            "SELECT person_id, live_depth FROM people WHERE live_depth IS NOT NULL").fetchall()
        return {r["person_id"]: float(r["live_depth"]) for r in rows}

    def list_people(self):
        return self._conn.execute(
            """
            SELECT p.person_id, p.name, p.created_at,
                   (SELECT COUNT(*) FROM face_templates f WHERE f.person_id=p.person_id) AS faces,
                   (SELECT COUNT(*) FROM finger_templates g WHERE g.person_id=p.person_id) AS fingers
            FROM people p ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()

    def rename_person(self, person_id: int, name: str):
        with self._lock:
            self._conn.execute("UPDATE people SET name=? WHERE person_id=?", (name, person_id))
            self._conn.commit()

    def delete_person(self, person_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM people WHERE person_id=?", (person_id,))
            self._conn.commit()

    # ---------------- face templates ----------------
    def add_face_template(self, person_id: int, blob: bytes):
        with self._lock:
            self._conn.execute(
                "INSERT INTO face_templates(person_id, embedding) VALUES (?, ?)",
                (person_id, blob),
            )
            self._conn.commit()

    def face_gallery(self):
        """Returns [(person_id, name, embedding_blob), ...] for matching."""
        return self._conn.execute(
            """
            SELECT f.person_id, p.name, f.embedding
            FROM face_templates f JOIN people p ON p.person_id = f.person_id
            """
        ).fetchall()

    # ---------------- finger templates ----------------
    def add_finger_template(self, person_id: int, module_slot: int):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO finger_templates(person_id, module_slot) VALUES (?, ?)",
                (person_id, module_slot),
            )
            self._conn.commit()

    def finger_map(self) -> dict[int, dict]:
        """slot -> {person_id, name}"""
        rows = self._conn.execute(
            """
            SELECT g.module_slot, g.person_id, p.name
            FROM finger_templates g JOIN people p ON p.person_id = g.person_id
            """
        ).fetchall()
        return {r["module_slot"]: {"person_id": r["person_id"], "name": r["name"]} for r in rows}

    # ---------------- events ----------------
    def log_event(self, person_id, name, method, result, score=0.0,
                  image_path=None, ts: Optional[str] = None) -> int:
        # accept either str or an enum (Method/Result) and store its value
        method = getattr(method, "value", method)
        result = getattr(result, "value", result)
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO events(person_id, name, ts, method, result, score, image_path)
                   VALUES (?,?,?,?,?,?,?)""",
                (person_id, name, ts or _now(), str(method), str(result), float(score), image_path),
            )
            self._conn.commit()
            return cur.lastrowid

    def query_events(self, name=None, date=None, method=None, result=None, limit=500):
        sql = "SELECT * FROM events WHERE 1=1"
        args: list = []
        if name:
            sql += " AND name LIKE ?"; args.append(f"%{name}%")
        if date:
            sql += " AND ts LIKE ?"; args.append(f"{date}%")
        if method:
            sql += " AND method=?"; args.append(method)
        if result:
            sql += " AND result=?"; args.append(result)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"; args.append(limit)
        return self._conn.execute(sql, args).fetchall()

    def recent_events(self, n=10):
        return self._conn.execute(
            "SELECT * FROM events ORDER BY ts DESC, id DESC LIMIT ?", (n,)
        ).fetchall()

    def entries_by_day(self, days: int = 30) -> list[tuple[str, int]]:
        """[(YYYY-MM-DD, granted_count)] for the last `days`, oldest first — for the
        entry graph on the dashboard."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT substr(ts,1,10) AS d, COUNT(*) AS c FROM events "
            "WHERE result='granted' AND substr(ts,1,10) >= ? GROUP BY d ORDER BY d",
            (cutoff,)).fetchall()
        return [(r["d"], r["c"]) for r in rows]

    def purge_events(self, days: int = 30) -> list[str]:
        """Delete events older than `days` (privacy: keep only the retention window).
        Returns the image paths of deleted rows so the caller can unlink the files."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            imgs = [r["image_path"] for r in self._conn.execute(
                "SELECT image_path FROM events WHERE ts < ? AND image_path IS NOT NULL",
                (cutoff,)).fetchall()]
            self._conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
            self._conn.commit()
        return imgs

    def intruders(self, limit=60):
        return self._conn.execute(
            "SELECT * FROM events WHERE image_path IS NOT NULL ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def get_event(self, event_id: int):
        return self._conn.execute(
            "SELECT * FROM events WHERE id=?", (event_id,)
        ).fetchone()

    def delete_event(self, event_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM events WHERE id=?", (event_id,))
            self._conn.commit()

    def stats_today(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        def c(where, *a):
            return self._conn.execute(
                f"SELECT COUNT(*) FROM events WHERE ts LIKE ? {where}", (f"{today}%", *a)
            ).fetchone()[0]
        return {
            "entries": c("AND result='granted'"),
            "denied": c("AND result LIKE 'denied-%'"),
            "spoof": c("AND result='denied-spoof'"),
            "enrolled": self._conn.execute("SELECT COUNT(*) FROM people").fetchone()[0],
        }

    # ---------------- users / auth ----------------
    def get_user(self, username: str):
        return self._conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

    def upsert_user(self, username: str, pw_hash: str):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO users(username, pw_hash) VALUES (?, ?)",
                (username, pw_hash),
            )
            self._conn.commit()

    def has_users(self) -> bool:
        return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
