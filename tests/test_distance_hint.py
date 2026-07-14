"""Phase 4: enrollment distance guidance — face-width fraction -> voice prompt."""
from acs.core.face_detect import FaceDetector


def test_too_close():
    assert FaceDetector.distance_hint(500, 640) == "stand_back"   # fills the frame


def test_too_far():
    assert FaceDetector.distance_hint(80, 640) == "come_closer"   # tiny face


def test_good_distance():
    assert FaceDetector.distance_hint(260, 640) is None           # ~0.4 -> fine


def test_no_frame_width():
    assert FaceDetector.distance_hint(100, 0) is None
