"""Phase 1: entry-graph query + 1-month retention purge."""
from datetime import datetime, timedelta

from acs.storage.db import DB


def _log(db, ts, result="granted", img=None):
    db.log_event(1, "X", "face", result, 0.5, img, ts=ts)


def test_entries_by_day_counts_only_granted(tmp_path):
    db = DB(tmp_path / "d.db"); db.init_schema()
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log(db, today); _log(db, today)
    _log(db, today, result="denied-unknown")          # must NOT be counted
    rows = db.entries_by_day(30)
    assert rows and rows[-1][1] == 2                   # 2 granted entries today


def test_purge_events_drops_old_and_returns_images(tmp_path):
    db = DB(tmp_path / "d.db"); db.init_schema()
    old = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    new = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _log(db, old, result="denied-spoof", img="data/unauthorized/old.jpg.enc")
    _log(db, new)
    imgs = db.purge_events(30)
    assert "data/unauthorized/old.jpg.enc" in imgs     # old image flagged for unlink
    rows = db.query_events()
    assert len(rows) == 1                              # only the recent event remains
