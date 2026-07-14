"""Guards the match() margin fix (Mythos v2 R-04): the ambiguity margin must
apply whenever a different person exists, and a clear/single match still works.
Pure numpy — no model needed (FaceRecognizer built via __new__)."""
import numpy as np

from acs.core.face_recognize import FaceRecognizer


def _rec():
    r = FaceRecognizer.__new__(FaceRecognizer)
    r._np = np
    r.cosine_thr = 0.363
    return r


def _unit(v):
    v = np.asarray(v, dtype="float32")
    return v / np.linalg.norm(v)


def test_clear_match():
    r = _rec()
    emb = _unit([1, 0, 0, 0])
    gallery = [(1, "A", _unit([1, 0, 0, 0])), (2, "B", _unit([0, 1, 0, 0]))]
    pid, name, _ = r.match(emb, gallery, margin=0.06)
    assert pid == 1 and name == "A"


def test_ambiguous_rejected():
    r = _rec()
    emb = _unit([1, 1, 0, 0])                       # ~equidistant to A and B
    gallery = [(1, "A", _unit([1, 0.9, 0, 0])), (2, "B", _unit([0.9, 1, 0, 0]))]
    pid, _, _ = r.match(emb, gallery, margin=0.06)
    assert pid is None                              # within margin -> ambiguous


def test_below_threshold_none():
    r = _rec()
    emb = _unit([1, 0, 0, 0])
    gallery = [(1, "A", _unit([0, 1, 0, 0]))]
    pid, _, _ = r.match(emb, gallery, margin=0.0)
    assert pid is None


def test_single_person_match_ok():
    r = _rec()
    emb = _unit([1, 0, 0, 0])
    gallery = [(1, "A", _unit([1, 0, 0, 0]))]       # no 'other' -> margin not applied
    pid, _, _ = r.match(emb, gallery, margin=0.06)
    assert pid == 1
