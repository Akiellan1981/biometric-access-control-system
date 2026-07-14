"""Guards the unified device path (Mythos): the headless door must act on the
SAME one-shot access-flow event the web path does — grant/spoof/deny_unknown —
mapping each to the correct DecisionEngine Candidate (no event -> nothing)."""
from acs.pipeline.face_thread import candidate_for_event
from acs.types import Method


def test_no_event_returns_none():
    assert candidate_for_event({"stage": "challenge"}, frame="f") is None
    assert candidate_for_event({"stage": "confirm", "event": None}, frame="f") is None


def test_grant_event():
    rec = {"event": "grant", "person_id": 7, "name": "Asha", "score": 0.81}
    c = candidate_for_event(rec, frame="f")
    assert c.person_id == 7 and c.method == Method.FACE and c.is_live is True
    assert c.name == "Asha" and c.score == 0.81 and c.frame == "f"


def test_spoof_event_is_not_live():
    rec = {"event": "spoof", "person_id": 7, "name": "Asha", "score": 0.4}
    c = candidate_for_event(rec, frame="f")
    assert c.person_id == 7 and c.is_live is False     # known face, failed challenge


def test_deny_unknown_event():
    rec = {"event": "deny_unknown", "score": 0.1}
    c = candidate_for_event(rec, frame="f")
    assert c.person_id is None and c.is_live is True   # unregistered -> denied, captured
