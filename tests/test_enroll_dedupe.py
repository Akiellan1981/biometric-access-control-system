"""Phase 2: one face must not be enrollable under two names.
duplicate_identity flags a new embedding that matches an existing DIFFERENT-named
person, while allowing re-registration of the SAME name. Pure numpy."""
import numpy as np

from acs.core.face_recognize import FaceRecognizer
from acs.web.live import duplicate_identity


def _rec():
    r = FaceRecognizer.__new__(FaceRecognizer)
    r._np = np
    r.cosine_thr = 0.363
    return r


def _unit(v):
    v = np.asarray(v, dtype="float32")
    return v / np.linalg.norm(v)


def test_same_face_different_name_is_flagged():
    rec = _rec()
    gallery = [(1, "Asha", _unit([1, 0, 0, 0]))]
    emb = _unit([1, 0, 0, 0])                         # same face, enrolling as "Bob"
    dup = duplicate_identity(rec, gallery, emb, "Bob")
    assert dup is not None and dup[1] == "Asha"


def test_same_name_reregistration_allowed():
    rec = _rec()
    gallery = [(1, "Asha", _unit([1, 0, 0, 0]))]
    emb = _unit([1, 0, 0, 0])                         # same face, SAME name -> allowed
    assert duplicate_identity(rec, gallery, emb, "Asha") is None


def test_new_face_not_flagged():
    rec = _rec()
    gallery = [(1, "Asha", _unit([1, 0, 0, 0]))]
    emb = _unit([0, 1, 0, 0])                         # different face -> fine
    assert duplicate_identity(rec, gallery, emb, "Bob") is None


def test_empty_gallery_ok():
    rec = _rec()
    assert duplicate_identity(rec, [], _unit([1, 0, 0, 0]), "Bob") is None
