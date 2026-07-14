"""Decision / logging engine (spec §8 consumer, FR-3.x, FR-4.x, FR-5.x).

This is the single place that writes events, so SQLite/Excel stay write-safe.
It is hardware-free and fully unit-testable: voice/relay/intruder are injected
and may be None.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from acs.types import Candidate, Method, Result

log = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(self, db, cfg, voice=None, relay=None, intruder=None):
        self.db = db
        self.voice = voice
        self.relay = relay
        self.intruder = intruder
        self.cooldown = float(cfg.get("decision.cooldown_seconds", 30))
        # Access-hold / re-verify interval: a grant is valid this long; after it the
        # person must verify again to be granted again. Dashboard-editable (DB key
        # 'grant_hold_seconds'); this is also how long re-grants are suppressed.
        self.grant_hold = float(cfg.get("decision.grant_hold_seconds", 5))
        self.finger_required = bool(cfg.get("decision.fingerprint_required_for_unlock", False))
        self.unknown_dedupe = float(cfg.get("intruder.dedupe_seconds", 20))
        self._last_grant: dict[int, float] = {}   # person_id -> ts (shared cooldown)
        self._last_unknown = 0.0
        self._lockout_until = 0.0                  # global: after a grant, ignore scans briefly

    def _hold(self) -> float:
        """Access-hold seconds — live-editable from the dashboard, else config."""
        try:
            v = self.db.get_setting("grant_hold_seconds", None)
            if v is not None:
                return float(v)
        except Exception:  # noqa: BLE001
            pass
        return self.grant_hold

    def handle(self, c: Candidate) -> Optional[Result]:
        """Process one candidate. Returns the Result, or None if suppressed."""
        # After a grant, repeat GRANTS are suppressed for the access-hold window so a
        # person who lingers isn't re-granted every frame — they must wait it out and
        # verify again. Denials/spoofs are NOT suppressed (a stranger right after a
        # grant must still be logged + captured; they have their own dedupe).
        would_grant = (c.person_id is not None
                       and not (c.method == Method.FACE and not c.is_live))
        if would_grant and time.time() < self._lockout_until:
            return None
        res = self._handle_known(c) if c.person_id is not None else self._handle_unknown(c)
        if res == Result.GRANTED:
            self._lockout_until = time.time() + self._hold()
        return res

    # ---------------- known person ----------------
    def _handle_known(self, c: Candidate) -> Optional[Result]:
        # A recognized face that fails liveness is a spoof of a known person.
        if c.method == Method.FACE and not c.is_live:
            return self._deny_face(c, Result.DENIED_SPOOF)

        now = time.time()
        hold = self._hold()
        last = self._last_grant.get(c.person_id, 0.0)
        if now - last < hold:                 # one grant per access-hold window
            log.debug("hold: suppressing %s for person %s", c.method, c.person_id)
            return None

        self._last_grant[c.person_id] = now
        if len(self._last_grant) > 256:   # keep the cooldown map from growing unbounded
            self._last_grant = {k: t for k, t in self._last_grant.items() if t >= now - hold}
        name = c.name or self._name(c.person_id)
        self.db.log_event(c.person_id, name, c.method, Result.GRANTED, c.score)
        if self.voice:
            self.voice.play("granted_finger" if c.method == Method.FINGERPRINT
                            else "granted_face")

        # FR-3.4: on critical doors, face logs presence but only fingerprint unlocks.
        may_unlock = (c.method == Method.FINGERPRINT) or (not self.finger_required)
        if self.relay and may_unlock:
            self.relay.pulse()
        log.info("GRANTED %s via %s (score=%.3f, unlock=%s)",
                 name, c.method.value, c.score, may_unlock)
        return Result.GRANTED

    # ---------------- unknown / failed ----------------
    def _handle_unknown(self, c: Candidate) -> Optional[Result]:
        if c.method == Method.FINGERPRINT:
            # finger read but did not resolve to a person — no image (FR-5.4)
            self.db.log_event(None, "unknown", c.method, Result.DENIED_FINGER, c.score)
            if self.voice:
                self.voice.play("denied_finger")     # "denied by fingerprint, please try again"
            log.info("DENIED-FINGER")
            return Result.DENIED_FINGER

        result = Result.DENIED_SPOOF if not c.is_live else Result.DENIED_UNKNOWN
        return self._deny_face(c, result)

    def _deny_face(self, c: Candidate, result: Result) -> Optional[Result]:
        now = time.time()
        if now - self._last_unknown < self.unknown_dedupe:
            return None
        self._last_unknown = now
        tag = "spoof" if result == Result.DENIED_SPOOF else "unknown"
        image_path = self.intruder.capture(c.frame, tag) if self.intruder else None
        name = c.name or self._name(c.person_id) if c.person_id else "unknown"
        self.db.log_event(c.person_id, name, c.method, result, c.score, image_path)
        if self.voice:
            # spoof / no-action = "movement not detected, try again"; unknown = denied.
            self.voice.play("denied_spoof" if result == Result.DENIED_SPOOF else "denied_face")
        log.info("%s (image=%s)", result.value, image_path)
        return result

    def _name(self, person_id) -> str:
        if person_id is None:
            return "unknown"
        row = self.db.get_person(person_id)
        return row["name"] if row else f"#{person_id}"
