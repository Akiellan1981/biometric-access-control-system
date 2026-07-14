"""Phase 3: status LED + dark-scene lamp logic (mock driver, no GPIO)."""
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np  # noqa: E402

from acs.config import Config  # noqa: E402
from acs.core.indicators import Indicators, frame_brightness  # noqa: E402


def _cfg():
    # both outputs disabled -> mock no-op outputs; lamp thresholds from defaults
    return Config({"lamp": {"dark_threshold": 60, "bright_margin": 15}}, Path("."))


def _frame(v):
    return np.full((20, 20, 3), v, dtype="uint8")


def test_frame_brightness():
    assert frame_brightness(_frame(0)) == 0.0
    assert frame_brightness(_frame(200)) > 150
    assert frame_brightness(None) == 0.0


def test_status_led_wake_sleep():
    ind = Indicators(_cfg())
    ind.wake();  assert ind.led.state is True
    ind.sleep(); assert ind.led.state is False and ind.lamp.state is False


def test_lamp_turns_on_in_dark_off_in_bright():
    ind = Indicators(_cfg())
    assert ind.update_light(_frame(10)) is True       # dark -> lamp on
    assert ind.update_light(_frame(200)) is False     # bright -> lamp off


def test_lamp_hysteresis_holds_in_band():
    ind = Indicators(_cfg())
    ind.update_light(_frame(10))                       # on (dark)
    # brightness in (dark_thr, dark_thr+margin] => no change, stays on
    assert ind.update_light(_frame(70)) is True
