-- Canonical schema (spec §9). Embeddings are stored, never raw face images.
CREATE TABLE IF NOT EXISTS people (
    person_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    live_depth REAL,                 -- self-calibrated real-face depth (this camera), set at enrollment
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS face_templates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
    embedding  BLOB NOT NULL,            -- encrypted float32[128] bytes
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS finger_templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id   INTEGER NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
    module_slot INTEGER NOT NULL UNIQUE, -- slot id on the sensor (match is on-sensor)
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id  INTEGER,
    name       TEXT NOT NULL,
    ts         TEXT NOT NULL,
    method     TEXT NOT NULL,            -- face | fingerprint
    result     TEXT NOT NULL,            -- granted | denied-unknown | denied-spoof | denied-finger
    score      REAL DEFAULT 0,
    image_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_result ON events(result);

CREATE TABLE IF NOT EXISTS users (
    username   TEXT PRIMARY KEY,
    pw_hash    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
