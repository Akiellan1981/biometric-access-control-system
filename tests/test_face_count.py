"""Guards the multi-face rejection helper (Mythos v2 R-01): more than one close
face -> the engine must refuse to commit an identity (fail-safe, never grant)."""
from acs.core.face_detect import FaceDetector


class _F:
    def __init__(self, w):
        self.w = w


def test_count_qualifying():
    faces = [_F(100), _F(40), _F(90)]
    assert FaceDetector.count_qualifying(faces, 80) == 2     # the 40px one is ignored
    assert FaceDetector.count_qualifying([], 80) == 0
    assert FaceDetector.count_qualifying([_F(80)], 80) == 1  # boundary inclusive
