"""Phase 5 resilience: a frozen/dead camera feed must read as 'no frame', not as
the last person seen (otherwise the door could keep acting on a stale image)."""
import time

from acs.config import Config
from acs.web.live import CameraHub


class _Frame:
    def copy(self):
        return self


def test_fresh_frame_returned():
    hub = CameraHub(Config({}, "."))
    hub._latest = _Frame()
    hub._last_ok = time.time()
    assert hub.frame() is not None


def test_stale_frame_treated_as_none():
    hub = CameraHub(Config({}, "."))
    hub._latest = _Frame()
    hub._last_ok = time.time() - 5.0          # older than the 2s staleness window
    assert hub.frame() is None


def test_no_frame_yet_is_none():
    hub = CameraHub(Config({}, "."))
    assert hub.frame() is None
