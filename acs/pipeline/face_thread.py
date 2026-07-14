"""Face producer thread (headless door) — UNIFIED with the dashboard path.

Spoof detection across the whole project is the MediaPipe challenge-response:
detection first ("recognised"), then a randomised blink / turn-left / turn-right
sequence the person must perform live. A printed photo or static phone image
cannot blink on cue in a random order, so it is rejected. (A pre-recorded video
replay is the known residual gap — add MiniFASNet/depth for that.)

This thread reuses the SAME `FaceEngine` + `AccessFlow` + `LivenessMonitor` the
web `/try` page uses (one implementation, one behaviour), and guides the person
by PRE-RECORDED VOICE instead of a screen via `ChallengeAnnouncer`. On a grant /
spoof / unknown event it emits a Candidate; the DecisionEngine logs it, voices
the outcome, and pulses the relay.

If models / ML deps are missing the engine is unavailable and the thread idles,
so the rest of the system keeps working in dev. On the Pi (dev_mode:false) a
missing liveness backend fails CLOSED (no silent grant).
"""
from __future__ import annotations

import logging
import threading
import time

from acs.types import Candidate, Method

log = logging.getLogger(__name__)


def candidate_for_event(rec: dict, frame) -> Candidate | None:
    """Map a FaceEngine.recognize() result to a DecisionEngine Candidate.

    Acts only on the one-shot `event` the access flow emits at each transition:
      grant        -> known + passed the live challenge  (is_live=True)
      spoof        -> known + failed/timed-out challenge  (is_live=False)
      deny_unknown -> unregistered face                   (person_id=None)
    Returns None when there is no event this tick. Pure + unit-tested."""
    ev = rec.get("event")
    if not ev:
        return None
    if ev == "grant":
        return Candidate(rec.get("person_id"), Method.FACE, rec.get("score", 0.0),
                         is_live=True, name=rec.get("name"), frame=frame)
    if ev == "spoof":
        return Candidate(rec.get("person_id"), Method.FACE, rec.get("score", 0.0),
                         is_live=False, name=rec.get("name"), frame=frame)
    return Candidate(None, Method.FACE, rec.get("score", 0.0), is_live=True, frame=frame)


class FaceThread(threading.Thread):
    def __init__(self, cfg, db, cipher, out_queue, stop_event, voice=None):
        super().__init__(name="face", daemon=True)
        self.cfg = cfg
        self.db = db
        self.q = out_queue
        self.stop = stop_event
        self.voice = voice
        self.enabled = False

        # Motion-gated camera power (PIR/IR): wake on motion, off after idle.
        self.motion_enabled = bool(cfg.get("motion.enabled", False))
        self._idle_off_default = float(cfg.get("motion.idle_off_seconds", 60))
        self.motion_poll = float(cfg.get("motion.poll_seconds", 0.2))
        self.motion = None
        self.hub = None
        self.engine = None
        self.announcer = None
        self._build(cfg, db, cipher, voice)

    def _build(self, cfg, db, cipher, voice):
        from acs.core.indicators import Indicators
        from acs.core.motion import create_motion
        from acs.core.voice import ChallengeAnnouncer
        from acs.web.live import CameraHub, FaceEngine
        self.motion = create_motion(cfg)
        self.indicators = Indicators(cfg)   # status LED + dark-scene lamp
        self.hub = CameraHub(cfg, db)        # db -> dashboard camera-source toggle
        # FaceEngine builds detector + recognizer + the liveness monitor, and (when
        # the monitor is available) starts the hub + monitor thread.
        self.engine = FaceEngine(cfg, db, cipher, self.hub)
        self.enabled = self.engine.available
        if not self.enabled:
            log.warning("face recognition disabled (%s)", self.engine.error)
        self.announcer = ChallengeAnnouncer(
            voice=voice, ack=bool(cfg.get("voice.challenge_ack", False)))

    def reload_gallery(self):
        if self.engine is not None:
            self.engine.reload_gallery()

    def _idle_off(self) -> float:
        """Camera idle-off seconds — live-editable from the dashboard (DB setting),
        falling back to config."""
        try:
            v = self.db.get_setting("idle_off_seconds", None)
            if v is not None:
                return float(v)
        except Exception:  # noqa: BLE001 - never let a bad setting break the loop
            pass
        return self._idle_off_default

    def run(self):
        if not self.enabled:
            log.info("face thread idle (recognition disabled)")
            self._idle()
            return
        if self.motion_enabled:
            self.hub.stop()                # powered down until motion wakes it
            awake = False
            self.announcer.reset()
            self.indicators.sleep()
        else:
            self.hub.start()               # idempotent; ensure the camera is on
            awake = True
            self.indicators.wake()
            self._welcome()
        last_motion = time.time()
        light_tick = 0

        while not self.stop.is_set():
            if self.motion_enabled:
                if self.motion.motion():
                    last_motion = time.time()
                    if not awake:
                        self.hub.start()
                        awake = True
                        self.indicators.wake()     # status LED on
                        self._welcome()            # spoken greeting on wake
                        log.info("camera ON (motion detected)")
                elif awake and (time.time() - last_motion) > self._idle_off():
                    self.hub.stop()
                    awake = False
                    self.announcer.reset()
                    self.indicators.sleep()        # status LED off, lamp off
                    log.info("camera OFF (idle, waiting for motion)")
                if not awake:
                    time.sleep(self.motion_poll)
                    continue

            frame = self.hub.frame()
            if frame is None:
                time.sleep(0.03)
                continue
            try:
                light_tick += 1
                if light_tick % 30 == 0:           # ~1/sec: lamp on if scene is dark
                    self.indicators.update_light(frame)
                rec = self.engine.recognize(frame)  # detect -> debounce -> challenge
                self.announcer.update(rec)          # speak the next instruction (if new)
                cand = candidate_for_event(rec, frame)
                if cand is not None:
                    self.q.put(cand)
            except Exception as e:  # noqa: BLE001 - one bad frame must not kill the door
                log.exception("face loop error (continuing): %s", e)
            time.sleep(0.03)
        self.indicators.close()                    # release GPIO on shutdown

    def _welcome(self):
        if self.voice is not None:
            self.voice.play("welcome")     # "stand in front / place finger"

    def _idle(self):
        while not self.stop.is_set():
            time.sleep(0.2)
