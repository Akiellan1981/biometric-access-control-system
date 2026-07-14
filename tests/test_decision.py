import time
from pathlib import Path

from acs.config import Config
from acs.core.decision import DecisionEngine
from acs.storage.db import DB
from acs.types import Candidate, Method, Result


class FakeVoice:
    def __init__(self): self.played = []
    def play(self, k): self.played.append(k)


class FakeRelay:
    def __init__(self): self.pulses = 0
    def pulse(self): self.pulses += 1


class FakeIntruder:
    def __init__(self): self.calls = []
    def capture(self, frame, tag): self.calls.append(tag); return f"{tag}.jpg"


def build(tmp_path, **over):
    db = DB(tmp_path / "d.db"); db.init_schema()
    data = {"decision": {"cooldown_seconds": 30, "fingerprint_required_for_unlock": False},
            "intruder": {"dedupe_seconds": 0}}
    data["decision"].update(over)
    cfg = Config(data, Path(tmp_path))
    voice, relay, intr = FakeVoice(), FakeRelay(), FakeIntruder()
    eng = DecisionEngine(db, cfg, voice=voice, relay=relay, intruder=intr)
    return db, eng, voice, relay, intr


def test_known_live_face_granted(tmp_path):
    db, eng, voice, relay, _ = build(tmp_path)
    pid = db.add_person("Asha")
    res = eng.handle(Candidate(pid, Method.FACE, 0.7, is_live=True, name="Asha"))
    assert res == Result.GRANTED
    assert relay.pulses == 1 and "granted_face" in voice.played   # method-specific clip
    assert db.query_events(result="granted")


def test_voice_clip_is_method_specific(tmp_path):
    # face vs fingerprint, grant vs deny -> distinct pre-recorded clips
    db, eng, voice, _, _ = build(tmp_path)
    pid = db.add_person("Asha")
    eng.handle(Candidate(pid, Method.FINGERPRINT, 0.9, is_live=True))
    assert "granted_finger" in voice.played

    db2, eng2, voice2, _, _ = build(tmp_path / "b")
    eng2.handle(Candidate(None, Method.FINGERPRINT, 0.3))          # unresolved finger
    assert "denied_finger" in voice2.played

    db3, eng3, voice3, _, _ = build(tmp_path / "c")
    eng3.handle(Candidate(None, Method.FACE, 0.1, is_live=True, frame=object()))  # unknown face
    assert "denied_face" in voice3.played


def test_cooldown_suppresses_second(tmp_path):
    db, eng, *_ = build(tmp_path)
    pid = db.add_person("Asha")
    c = Candidate(pid, Method.FACE, 0.7, is_live=True)
    assert eng.handle(c) == Result.GRANTED
    assert eng.handle(c) is None                    # within cooldown
    assert len(db.query_events()) == 1


def test_recognized_but_spoof(tmp_path):
    db, eng, _, _, intr = build(tmp_path)
    pid = db.add_person("Asha")
    res = eng.handle(Candidate(pid, Method.FACE, 0.7, is_live=False, frame=object()))
    assert res == Result.DENIED_SPOOF and intr.calls == ["spoof"]


def test_unknown_face(tmp_path):
    db, eng, _, _, intr = build(tmp_path)
    res = eng.handle(Candidate(None, Method.FACE, 0.1, is_live=True, frame=object()))
    assert res == Result.DENIED_UNKNOWN and intr.calls == ["unknown"]


def test_fingerprint_unresolved(tmp_path):
    db, eng, *_ = build(tmp_path)
    res = eng.handle(Candidate(None, Method.FINGERPRINT, 0.4))
    assert res == Result.DENIED_FINGER
    assert db.query_events(result="denied-finger")


def test_finger_required_face_logs_but_no_unlock(tmp_path):
    db, eng, _, relay, _ = build(tmp_path, fingerprint_required_for_unlock=True)
    pid = db.add_person("Asha")
    res = eng.handle(Candidate(pid, Method.FACE, 0.7, is_live=True))
    assert res == Result.GRANTED and relay.pulses == 0     # presence logged, no unlock


def test_regrant_allowed_after_access_hold(tmp_path):
    # access-hold = 0 -> the same person can be granted again immediately (re-verify)
    db, eng, _, relay, _ = build(tmp_path, grant_hold_seconds=0)
    pid = db.add_person("Asha")
    c = Candidate(pid, Method.FACE, 0.7, is_live=True)
    assert eng.handle(c) == Result.GRANTED
    assert eng.handle(c) == Result.GRANTED      # re-granted after the (zero) hold
    assert relay.pulses == 2


def test_no_regrant_within_access_hold(tmp_path):
    # a large hold suppresses re-grant until the person verifies again later
    db, eng, _, relay, _ = build(tmp_path, grant_hold_seconds=60)
    pid = db.add_person("Asha")
    c = Candidate(pid, Method.FACE, 0.7, is_live=True)
    assert eng.handle(c) == Result.GRANTED
    assert eng.handle(c) is None                 # still within the access-hold window
    assert relay.pulses == 1


def test_rescan_lockout_blocks_regrant_not_denial(tmp_path):
    # After a grant, the rescan lockout suppresses a repeat GRANT, but a stranger
    # who steps up within the window must STILL be denied + captured (not silenced).
    db, eng, _, _, intr = build(tmp_path, rescan_delay_seconds=5)
    pid = db.add_person("Asha")
    assert eng.handle(Candidate(pid, Method.FACE, 0.7, is_live=True)) == Result.GRANTED

    pid2 = db.add_person("Bob")                              # a different known person
    assert eng.handle(Candidate(pid2, Method.FACE, 0.7, is_live=True)) is None  # re-grant suppressed

    res = eng.handle(Candidate(None, Method.FACE, 0.1, is_live=True, frame=object()))
    assert res == Result.DENIED_UNKNOWN                      # stranger NOT silenced
    assert "unknown" in intr.calls                           # and captured
