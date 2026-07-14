"""Fingerprint producer thread: poll sensor, resolve slot -> person, emit candidate."""
from __future__ import annotations

import logging
import threading
import time

from acs.types import Candidate, Method

log = logging.getLogger(__name__)


class FingerThread(threading.Thread):
    def __init__(self, cfg, db, sensor, out_queue, stop_event):
        super().__init__(name="finger", daemon=True)
        self.cfg = cfg
        self.db = db
        self.sensor = sensor
        self.q = out_queue
        self.stop = stop_event
        self.poll = float(cfg.get("fingerprint.poll_seconds", 0.4))

    def run(self):
        while not self.stop.is_set():
            try:
                match = self.sensor.search()
            except Exception as e:  # noqa: BLE001
                log.warning("fingerprint search error: %s", e)
                match = None
            if match is not None:
                self._emit(match)
            time.sleep(self.poll)

    def _emit(self, match):
        entry = self.db.finger_map().get(match.slot)
        score = match.confidence / 100.0
        if entry:                                   # FR-2.3 independent grant
            self.q.put(Candidate(entry["person_id"], Method.FINGERPRINT, score,
                                 is_live=True, name=entry["name"]))
        else:                                       # matched a slot with no person
            self.q.put(Candidate(None, Method.FINGERPRINT, score))
