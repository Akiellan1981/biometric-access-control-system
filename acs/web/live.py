"""Live camera + face engine for the browser 'Try' page.

A single CameraHub owns the webcam (one process, one reader thread) so the MJPEG
preview, enrollment capture, and live recognition all share the same frames
without fighting over the device. FaceEngine wraps YuNet + SFace + the gallery.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque

log = logging.getLogger(__name__)


def duplicate_identity(recognizer, gallery, emb, name):
    """If `emb` matches an already-enrolled person with a DIFFERENT name, return
    (person_id, name) of that person. Used at enrollment to stop ONE face being
    registered under TWO names. Re-registering the SAME name is allowed (excluded
    here). Returns None when there is no different-named match."""
    target = (name or "").strip().lower()
    others = [(pid, nm, g) for (pid, nm, g) in gallery
              if (nm or "").strip().lower() != target]
    if not others:
        return None
    pid, mname, _ = recognizer.match(emb, others)
    return (pid, mname) if pid is not None else None


class CameraHub:
    """Owns the camera; keeps the latest frame available to everyone."""

    def __init__(self, cfg, db=None):
        self.cfg = cfg
        self.db = db                  # for the dashboard camera-source toggle
        self._cam = None
        self._latest = None
        self._last_ok = 0.0
        self._fail = 0
        self._lock = threading.Lock()
        self._running = False

    def _source(self):
        if self.db is not None:
            try:
                return self.db.get_setting("camera_source", None)
            except Exception:  # noqa: BLE001
                return None
        return None

    def start(self):
        if self._running:
            return
        from acs.core.camera import open_camera
        self._cam = open_camera(self.cfg, source=self._source())
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        time.sleep(0.5)  # let the first frames arrive

    def _loop(self):
        from acs.core.camera import open_camera
        while self._running:
            try:
                frame = self._cam.read()
            except Exception as e:  # noqa: BLE001 - a camera glitch must not kill the reader
                frame = None
                log.warning("camera read error: %s", e)
            if frame is not None:
                with self._lock:
                    self._latest = frame
                    self._last_ok = time.time()
                self._fail = 0
            else:
                self._fail += 1
                if self._fail % 150 == 0:        # ~5s of failure -> try to reopen
                    log.warning("camera produced no frame (x%d); reopening", self._fail)
                    try:
                        if self._cam:
                            self._cam.release()
                        self._cam = open_camera(self.cfg, source=self._source())
                    except Exception as e:  # noqa: BLE001
                        log.warning("camera reopen failed: %s", e)
            time.sleep(0.03)

    def frame(self):
        with self._lock:
            # Treat a frozen feed as "no frame" so recognition never acts on a stale
            # image (a dead camera must NOT keep showing the last person seen).
            if self._latest is None or (time.time() - self._last_ok) > 2.0:
                return None
            return self._latest.copy()

    def stop(self):
        self._running = False
        if self._cam:
            self._cam.release()


class LivenessMonitor(threading.Thread):
    """Continuously samples the camera (~15 fps) and tracks an ACTIVE liveness
    signal — a real eye-blink — which a printed photo or a static screen cannot
    fake. Running in its own thread decouples liveness from the slow recognize()
    poll, so blinks (≈150 ms) are never missed. Also publishes the latest face
    landmarks so the enrollment mesh reuses this single FaceLandmarker."""

    def __init__(self, cfg, hub, models_dir):
        super().__init__(name="liveness", daemon=True)
        self.hub = hub
        self.ear_thr = float(cfg.get("liveness.blink_ear_thr", 0.21))       # "clearly closed"
        self.open_thr = float(cfg.get("liveness.blink_open_thr", 0.27))      # "clearly open"
        self.blink_drop = float(cfg.get("liveness.blink_min_drop", 0.08))    # min EAR dip for a real blink
        # model blendshape eyeBlink thresholds (preferred over EAR; ~0=open, 1=closed)
        self.bs_close = float(cfg.get("liveness.blink_shape_close", 0.50))
        self.bs_open = float(cfg.get("liveness.blink_shape_open", 0.30))
        self.window = float(cfg.get("liveness.active_window_seconds", 4.0))
        self.spoof_after = float(cfg.get("liveness.spoof_timeout_seconds", 6.0))
        self.depth_thr = float(cfg.get("liveness.passive_depth_thr", 0.80))
        # When False, depth NEVER grants on its own -> EVERYONE does the blink+turn
        # challenge (most consistent, threshold-independent). True = instant on a 3D face.
        self.depth_fast_pass = bool(cfg.get("liveness.depth_fast_pass", False))
        self.turn_thr = float(cfg.get("liveness.turn_range_thr", 0.18))
        self.turn_dir_thr = float(cfg.get("liveness.turn_dir_thr", 0.10))   # yaw dev for a directional turn
        self.turn_invert = bool(cfg.get("liveness.turn_invert", False))      # swap if L/R feels reversed
        self.verify_hold = float(cfg.get("liveness.verify_hold_seconds", 5.0))
        self.smooth_n = int(cfg.get("liveness.depth_smooth_frames", 7))
        self._lm = None
        try:
            from acs.core.facemesh import FaceLandmarks
            self._lm = FaceLandmarks(models_dir, mode="video")   # tracked = consistent
        except Exception as e:  # noqa: BLE001
            log.warning("liveness monitor disabled: %s", e)
        self.available = self._lm is not None
        self._lock = threading.Lock()
        n = max(20, int(self.window / 0.03))
        self._yaws = deque(maxlen=n)               # recent head-yaw ratios (turn detection)
        self._depths = deque(maxlen=max(3, self.smooth_n))   # for median smoothing
        self._eye_open = True                      # hysteresis blink state machine
        self._closed_min = 1.0                     # lowest EAR seen during a closure
        self._baseline = 0.30                      # adaptive open-eye EAR baseline
        self._last_blink = 0.0
        self._challenge_at = 0.0                   # last moment blink AND turn held together
        self._last_turn_left = 0.0                 # directional turn event timestamps
        self._last_turn_right = 0.0
        self._blink_count = 0                      # monotonic action counters (resolution-proof)
        self._turn_left_count = 0
        self._turn_right_count = 0
        self._yaw_base = None                      # adaptive neutral yaw
        self._turned_side = None                   # debounce: 'l'/'r' while turned
        self._face_since = 0.0
        self._last_face_ts = 0.0                   # last time a face was actually seen
        self._lost_grace = float(cfg.get("liveness.face_lost_grace_seconds", 0.5))
        self._face = False
        self._depth = 0.0                          # SMOOTHED depth (median)
        self._landmarks = None
        self._stop = False

    @staticmethod
    def _median(vals):
        s = sorted(vals)
        n = len(s)
        if n == 0:
            return 0.0
        m = n // 2
        return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])

    def run(self):
        if not self.available:
            return
        from acs.core.liveness import _ear, _LEFT_EYE, _RIGHT_EYE
        while not self._stop:
            frame = self.hub.frame()
            if frame is None:
                time.sleep(0.05)
                continue
            pts3, blend = self._lm.detect_full(frame)
            now = time.time()
            if not pts3:
                with self._lock:
                    self._face = False
                    self._landmarks = None
                    self._depths.clear()
                    self._yaws.clear()
                    self._eye_open = True
                    self._closed_min = 1.0
                    self._yaw_base = None
                    self._turned_side = None
                    # Drop a verified session only once the face has truly been gone past
                    # the grace window — tolerates 1-frame detector dropouts (no flicker)
                    # but still blocks a verified-person -> photo swap.
                    if (now - self._last_face_ts) > self._lost_grace:
                        self._face_since = 0.0
                        self._challenge_at = 0.0
                        self._last_blink = 0.0
                time.sleep(0.04)
                continue
            xs = [p[0] for p in pts3]
            zs = [p[2] for p in pts3]
            fw = (max(xs) - min(xs)) or 1e-6
            depth = (max(zs) - min(zs)) / fw
            # yaw proxy: nose-tip x position between the two cheek edges (0=one side,
            # 1=other). Turning the head sweeps this value; a flat photo can't.
            yaw = (pts3[1][0] - pts3[234][0]) / ((pts3[454][0] - pts3[234][0]) or 1e-6)
            h, w = frame.shape[:2]
            pts = [(int(p[0] * w), int(p[1] * h)) for p in pts3]
            ear = (_ear(pts, _LEFT_EYE) + _ear(pts, _RIGHT_EYE)) / 2.0
            with self._lock:
                if not self._face:
                    self._face_since = now
                    self._eye_open = True
                    self._closed_min = 1.0
                self._face = True
                self._last_face_ts = now
                self._landmarks = pts
                self._depths.append(depth)
                self._yaws.append(yaw)

                # Directional turn events (for the randomized challenge): detect when
                # yaw deviates past a threshold from an adaptive neutral, once per turn.
                if self._yaw_base is None:
                    self._yaw_base = yaw
                dev = yaw - self._yaw_base
                rearm = self.turn_dir_thr * 0.5           # must return well inside neutral
                if self._turned_side is None:
                    # armed: a clear deviation past the threshold counts ONE turn
                    if dev > self.turn_dir_thr:
                        self._mark_turn("right", now)
                        self._turned_side = "r"
                    elif dev < -self.turn_dir_thr:
                        self._mark_turn("left", now)
                        self._turned_side = "l"
                    else:
                        self._yaw_base = 0.9 * self._yaw_base + 0.1 * yaw   # recenter
                elif abs(dev) < rearm:
                    # only re-arm once the head has returned near neutral (hysteresis),
                    # so jitter at the threshold can't double-count one head turn
                    self._turned_side = None

                # Blink: prefer the model's eyeBlink blendshape (robust), with a
                # hysteresis state machine. Fall back to EAR geometry if absent.
                bscore = None
                if blend is not None:
                    bscore = max(blend.get("eyeBlinkLeft", 0.0),
                                 blend.get("eyeBlinkRight", 0.0))
                if bscore is not None:
                    if self._eye_open:
                        if bscore > self.bs_close:
                            self._eye_open = False
                    else:
                        if bscore < self.bs_open:
                            self._last_blink = now      # closed -> open == one blink
                            self._blink_count += 1
                            self._eye_open = True
                else:
                    # EAR fallback with adaptive baseline + magnitude check.
                    if self._eye_open and ear > self.ear_thr:
                        self._baseline = 0.92 * self._baseline + 0.08 * ear
                    if self._eye_open:
                        if ear < self.ear_thr:
                            self._eye_open = False
                            self._closed_min = ear
                    else:
                        self._closed_min = min(self._closed_min, ear)
                        if ear > self.open_thr:
                            if (self._baseline - self._closed_min) >= self.blink_drop:
                                self._last_blink = now
                                self._blink_count += 1
                            self._eye_open = True

                # Smoothed depth + latch a passed challenge so it stays stable.
                self._depth = self._median(self._depths)
                blinked = (now - self._last_blink) < self.window
                turned = (len(self._yaws) >= 5
                          and (max(self._yaws) - min(self._yaws)) >= self.turn_thr)
                if blinked and turned:
                    self._challenge_at = now
            time.sleep(0.03)                          # ~ as fast as inference allows

    def snapshot(self, depth_thr: float | None = None) -> dict:
        with self._lock:
            now = time.time()
            depth = self._depth                       # already median-smoothed
            # FAST-PASS (optional): a clearly 3D face is live instantly. Disabled by
            # default -> the blink+turn challenge gates EVERYONE (threshold-independent).
            if self.depth_fast_pass:
                thr = self.depth_thr if depth_thr is None else depth_thr
                fast = self._face and depth >= thr
            else:
                fast = False
            blinked = (now - self._last_blink) < self.window
            turned = (len(self._yaws) >= 5
                      and (max(self._yaws) - min(self._yaws)) >= self.turn_thr)
            # CHALLENGE pass is LATCHED for verify_hold seconds -> stable, no flicker.
            challenge_live = (now - self._challenge_at) < self.verify_hold
            live = bool(self._face and (fast or challenge_live))
            needs_challenge = bool(self._face and not fast and not challenge_live)
            held = now - max(self._face_since, self._challenge_at)
            spoof = bool(needs_challenge and held > self.spoof_after)
            return {
                "face": self._face,
                "depth": round(float(depth), 3),
                "fast": bool(fast),
                "blinked": bool(blinked),
                "turned": bool(turned),
                "live": live,
                "needs_challenge": needs_challenge and not spoof,
                "spoof": spoof,
                "landmarks": self._landmarks,
            }

    def _mark_turn(self, side: str, now: float):
        if self.turn_invert:
            side = "left" if side == "right" else "right"
        if side == "left":
            self._last_turn_left = now
            self._turn_left_count += 1
        else:
            self._last_turn_right = now
            self._turn_right_count += 1

    def events(self) -> dict:
        """Monotonic action COUNTERS for the challenge (resolution-independent)."""
        with self._lock:
            return {"blink": self._blink_count, "turn_left": self._turn_left_count,
                    "turn_right": self._turn_right_count, "face": self._face}

    def enroll_live(self, window: float) -> bool:
        """Liveness gate for ENROLLMENT: requires a real blink within `window` seconds
        (proves a live person). Only when depth_fast_pass is on does a clearly 3D face
        also qualify. A photo passes neither."""
        with self._lock:
            if not self._face:
                return False
            recent_blink = (time.time() - self._last_blink) < window
            if recent_blink:
                return True
            return bool(self.depth_fast_pass and self._depth >= self.depth_thr)

    def stop_monitor(self):
        self._stop = True


class AccessFlow:
    """Per-session access state machine (detection FIRST, then liveness):

        idle --(registered face)--> confirm "{name}, is that you?"
             --(gap seconds)------> challenge: N random actions, total `timeout` budget
             --(all done)---------> granted        (event 'grant')
             --(timed out)--------> spoof + capture (event 'spoof')
        idle --(unregistered)-----> denied_unknown  (event 'deny_unknown', NO liveness)

    A terminal state (granted/spoof/denied_unknown) holds until the face leaves.
    Emits a one-shot `event` so the caller drives the decision engine exactly once."""

    LABELS = {"blink": "Blink", "turn_left": "Turn head LEFT", "turn_right": "Turn head RIGHT"}
    POOL = ["blink", "turn_left", "turn_right"]

    def __init__(self, steps=2, gap=2.0, timeout=10.0, pool=None, retry_hold=3.0,
                 grant_hold=5.0):
        pool = list(self.POOL if pool is None else pool)   # [] stays empty -> raises
        if not pool:
            raise ValueError("AccessFlow pool must be non-empty")
        self.pool = pool
        self.steps = max(1, min(int(steps), len(pool)))
        self.gap = float(gap)                # kept for compat; confirm stage removed
        self.timeout = float(timeout)
        self.retry_hold = float(retry_hold)  # spoof auto-recovers after this -> retry
        self.grant_hold = float(grant_hold)  # access valid this long -> then re-verify
        self.reset()

    def reset(self):
        self.state = "idle"
        self.pid = None
        self.name = None
        self.subject = None         # who the machine is committed to (pid:int or "unknown")
        self.seq: list[str] = []
        self.idx = 0
        self.t_state = 0.0
        self.base: dict = {}        # action counters captured at the current step's start

    def _start_challenge(self, now, counts):
        import random
        self.seq = random.sample(self.pool, self.steps)   # distinct, random order
        self.idx = 0
        self.state = "challenge"
        self.t_state = now
        self.base = dict(counts)    # current action must INCREMENT a counter past this

    def step(self, face_present, pid, name, events, can_challenge=True, fail_open=False):
        """Advance one tick. Re-derives the subject EVERY tick so a new/different
        person (or a stranger) is always processed fresh and never inherits the
        previous person's grant. Returns a view dict with a one-shot `event`.

        `fail_open` only matters when `can_challenge` is False (no liveness backend):
        True (dev) grants after confirm for convenience; False (production) fails
        CLOSED — a face we cannot liveness-check is treated as a spoof, never granted."""
        now = time.time()
        ev = None
        if not face_present:                 # nobody there -> idle
            if self.state != "idle":
                self.reset()
            return self._view(ev)

        subject = pid if pid is not None else "unknown"
        # A different subject than the one we're committed to -> abandon the old
        # result and start fresh. This MUST be immediate (no multi-frame hold):
        # after a grant the browser freezes for 5s and polls only ONCE when it
        # resumes, so any delayed reset would keep showing the previous person's
        # "granted" to whoever is now in front of the camera AND re-arm the freeze
        # every cycle -> a stranger would see a permanent grant. Returning the
        # neutral (idle) view stops the client freezing; the new person is then
        # debounced (FaceEngine._id_hist) and evaluated cleanly over later frames.
        if self.state != "idle" and subject != self.subject:
            self.reset()
            return self._view(ev)        # neutral idle view, no event

        # Terminal states. A spoof AUTO-RECOVERS after retry_hold so the page goes
        # back to checking and the person can retry the actions without walking away
        # (previously it stuck on 'spoof' forever for the same face). granted and
        # denied_unknown hold until the subject leaves / changes.
        if self.state == "spoof" and (now - self.t_state) > self.retry_hold:
            self.reset()                              # spoof -> retry; fall through
        elif self.state == "granted" and (now - self.t_state) > self.grant_hold:
            self.reset()                              # access expired -> must re-verify
        elif self.state in ("granted", "spoof", "denied_unknown"):
            return self._view(ev)

        if self.state == "idle":
            self.subject = subject
            if pid is not None:
                self.pid, self.name = pid, name
                # No "is that you?" step — go STRAIGHT to the 2 random actions.
                if can_challenge:
                    self._start_challenge(now, events)
                elif fail_open:                       # dev only: no backend -> grant
                    self.state, self.t_state, ev = "granted", now, "grant"
                else:                                 # production: no backend -> fail CLOSED
                    self.state, self.t_state, ev = "spoof", now, "spoof"
            else:
                self.state, self.t_state, ev = "denied_unknown", now, "deny_unknown"

        elif self.state == "challenge":
            action = self.seq[self.idx]
            if events.get(action, 0) > self.base.get(action, 0):   # a NEW action since prompt
                self.idx += 1
                self.base = dict(events)
                if self.idx >= len(self.seq):
                    self.state, self.t_state, ev = "granted", now, "grant"
            elif now - self.t_state > self.timeout:                # not done in budget -> spoof
                self.state, self.t_state, ev = "spoof", now, "spoof"

        return self._view(ev)

    def _view(self, ev):
        v = {"stage": self.state, "event": ev, "flow_name": self.name}
        if self.state == "challenge":
            v["prompt"] = (self.LABELS.get(self.seq[self.idx], self.seq[self.idx])
                           if self.idx < len(self.seq) else "Verified")
            v["seq"] = [self.LABELS.get(a, a) for a in self.seq]
            v["step"] = self.idx
            # raw action key (blink/turn_left/turn_right) so a voice-guided door can
            # speak the right pre-recorded clip for the current step.
            v["action"] = self.seq[self.idx] if self.idx < len(self.seq) else None
        return v


class FaceEngine:
    """Detect + recognize + enroll using the shared CameraHub."""

    def __init__(self, cfg, db, cipher, hub: CameraHub):
        self.cfg = cfg
        self.db = db
        self.cipher = cipher
        self.hub = hub
        self.available = False
        self.error = None
        self.min_w = cfg.get("face.min_face_width_px", 80)
        self.detector = None
        self.recognizer = None
        self.liveness = None
        self.monitor = None
        self._rec_lock = threading.Lock()   # serialize concurrent /try/recognize polls
        self.require_blink = bool(cfg.get("liveness.require_blink", True))
        # dev_mode = fail-open when no liveness backend (PC convenience). On the Pi
        # this is False, so a missing liveness backend fails CLOSED (no silent grant).
        self.dev_mode = bool(cfg.get("dev_mode", False))
        self.enroll_live_window = float(cfg.get("liveness.enroll_live_window_seconds", 20.0))
        # Access flow: detection FIRST, then randomized challenge liveness.
        self.flow = AccessFlow(
            steps=int(cfg.get("liveness.challenge_steps", 2)),
            gap=float(cfg.get("liveness.confirm_gap_seconds", 2.0)),
            timeout=float(cfg.get("liveness.challenge_timeout_seconds", 10.0)),
            retry_hold=float(cfg.get("liveness.retry_hold_seconds", 3.0)),
            grant_hold=float(cfg.get("decision.grant_hold_seconds", 5.0)),
        )
        self._gh_ts = 0.0   # throttle for refreshing grant_hold from the DB setting
        # Detection debounce: require the SAME identity over N frames before committing,
        # so a single mis-read never grants/denies the wrong person.
        self.detect_confirm = max(1, int(cfg.get("face.detect_confirm_frames", 3)))
        self._id_hist = deque(maxlen=self.detect_confirm)
        self.match_margin = float(cfg.get("face.match_margin", 0.0))
        self.enroll_min_blur = float(cfg.get("face.enroll_min_blur", 0.0))
        self.enroll_bright = (float(cfg.get("face.enroll_bright_min", 0)),
                              float(cfg.get("face.enroll_bright_max", 255)))
        # Self-calibrated liveness: per-person fast-pass = enrolled depth * factor
        # (floored so a photo's ~0 depth can never pass).
        self.live_depth_factor = float(cfg.get("liveness.live_depth_factor", 0.7))
        self.live_depth_floor = float(cfg.get("liveness.live_depth_floor", 0.15))
        self.live_depths: dict[int, float] = {}
        self._clahe = None
        self.gallery = []
        self._build()

    def _person_depth_thr(self, pid):
        """Self-calibrated fast-pass threshold for a known person, else None (global)."""
        base = self.live_depths.get(pid) if pid is not None else None
        if not base:
            return None
        return max(self.live_depth_floor, base * self.live_depth_factor)

    def _build(self):
        models = self.cfg.path("paths.models")
        try:
            from acs.core.face_detect import FaceDetector
            from acs.core.face_recognize import FaceRecognizer
            self.detector = FaceDetector(
                models / self.cfg.get("face.detect_model"),
                score_thr=self.cfg.get("face.detect_score_thr", 0.8),
            )
            self.recognizer = FaceRecognizer(
                models / self.cfg.get("face.recog_model"),
                cosine_thr=self.cfg.get("face.recognition_cosine_thr", 0.363),
            )
            self.reload_gallery()
            self.available = True
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            log.warning("FaceEngine unavailable: %s", e)
            return
        # Active blink monitor (continuous, ~15 fps) — the primary anti-spoof gate.
        try:
            self.monitor = LivenessMonitor(self.cfg, self.hub, models)
            if self.monitor.available:
                self.hub.start()
                self.monitor.start()
            else:
                self.monitor = None
        except Exception as e:  # noqa: BLE001
            log.warning("liveness monitor disabled: %s", e)
            self.monitor = None
        # Single-frame depth/MiniFASNet checker is only a FALLBACK — build it only when
        # the monitor is unavailable or require_blink is off (avoids a 2nd FaceLandmarker).
        if self.monitor is None or not self.require_blink:
            try:
                from acs.core.liveness import LivenessChecker
                self.liveness = LivenessChecker(self.cfg, models)
                log.info("liveness backend: %s", self.liveness.kind)
            except Exception as e:  # noqa: BLE001
                log.warning("liveness disabled: %s", e)

    def reload_gallery(self):
        self.gallery = [
            (r["person_id"], r["name"],
             self.recognizer.from_blob(self.cipher.decrypt(r["embedding"])))
            for r in self.db.face_gallery()
        ]
        self.live_depths = self.db.live_depths()   # self-calibrated per-person baselines

    def _largest(self, frame):
        from acs.core.face_detect import FaceDetector
        return FaceDetector.largest(self.detector.detect(frame), self.min_w)

    def _enhance(self, frame):
        """Normalize brightness/contrast (CLAHE on the L channel) so the same
        person matches in dark AND bright light. Geometry is unchanged, so the
        YuNet landmarks still align — applied identically at enroll and recognize."""
        try:
            import cv2
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            if self._clahe is None:
                self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            l = self._clahe.apply(l)
            return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        except Exception:  # noqa: BLE001
            return frame

    def _good_quality(self, frame, face) -> bool:
        """Reject blurry / badly-exposed enrollment crops so the gallery stays clean.
        Enrollment-only — no runtime cost. Disabled if thresholds are 0/defaults."""
        if self.enroll_min_blur <= 0 and self.enroll_bright == (0, 255):
            return True
        try:
            import cv2
            x, y, w, h = int(face.x), int(face.y), int(face.w), int(face.h)
            crop = frame[max(0, y):y + h, max(0, x):x + w]
            if crop.size == 0:
                return False
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            blur = cv2.Laplacian(gray, cv2.CV_64F).var()   # focus measure
            bright = float(gray.mean())
            return (blur >= self.enroll_min_blur
                    and self.enroll_bright[0] <= bright <= self.enroll_bright[1])
        except Exception:  # noqa: BLE001
            return True

    def _is_live(self, frame, face) -> bool:
        # Prefer the active blink monitor (real person), fall back to depth.
        if self.require_blink and self.monitor is not None:
            return bool(self.monitor.snapshot()["live"])
        if self.liveness is None:
            return True   # backend unavailable -> can't enforce (dev only)
        live, _ = self.liveness.check(frame, face)
        return bool(live)

    def _enroll_live(self, frame, face) -> bool:
        # Enrollment proves liveness over the whole session, not per-frame.
        if self.require_blink and self.monitor is not None:
            return self.monitor.enroll_live(self.enroll_live_window)
        return self._is_live(frame, face)

    def recognize(self, frame) -> dict:
        # Serialize: FastAPI may serve two /try/recognize polls on different threads,
        # and both mutate _id_hist + the flow. A lock keeps the state machine sane.
        with self._rec_lock:
            if frame is None:
                return {"ok": False, "error": "no frame"}
            # refresh dashboard-set timers (access-hold + spoof timeout) every ~2s
            now_gh = time.time()
            if now_gh - self._gh_ts > 2.0:
                self._gh_ts = now_gh
                try:
                    gh = self.db.get_setting("grant_hold_seconds", None)
                    if gh is not None:
                        self.flow.grant_hold = float(gh)
                    ct = self.db.get_setting("challenge_timeout_seconds", None)
                    if ct is not None:
                        self.flow.timeout = float(ct)   # actions not done within this -> spoof
                except Exception:  # noqa: BLE001
                    pass
            from acs.core.face_detect import FaceDetector
            dets = self.detector.detect(frame)
            face = FaceDetector.largest(dets, self.min_w)
            if face is None:
                self._id_hist.clear()
                self.flow.step(False, None, None, {})
                return {"ok": True, "name": None, "score": 0.0, "face": False, "stage": "idle"}

            # FAIL-SAFE: with more than one close face we cannot bind the liveness
            # signal (from the single-face monitor) to the right identity, so commit
            # nothing and ask for one person at a time. Never grants on ambiguity.
            if FaceDetector.count_qualifying(dets, self.min_w) > 1:
                self._id_hist.clear()
                self.flow.step(False, None, None, {})   # drop any in-progress subject
                box = [int(face.x), int(face.y), int(face.w), int(face.h)]
                return {"ok": True, "face": True, "name": None, "person_id": None,
                        "score": 0.0, "stage": "detecting", "box": box, "multi_face": True}

            # DETECTION FIRST — identify, then DEBOUNCE over a few frames so a momentary
            # mis-read can never grant/deny the wrong person ("no hurry in the check").
            emb = self.recognizer.embed(self._enhance(frame), face.raw)
            pid, name, score = self.recognizer.match(emb, self.gallery, margin=self.match_margin)
            self._id_hist.append(pid)
            stable = (len(self._id_hist) == self._id_hist.maxlen
                      and len(set(self._id_hist)) == 1)

            box = [int(face.x), int(face.y), int(face.w), int(face.h)]
            if self.flow.state == "idle" and not stable:
                # still confirming who it is -> commit nothing yet
                return {"ok": True, "face": True, "name": None, "person_id": None,
                        "score": round(float(score), 3), "stage": "detecting", "box": box}

            if stable:
                pid_use, name_use = pid, name
            elif self.flow.state in ("granted", "spoof", "denied_unknown"):
                # Terminal state: use the raw current-frame pid so step() can detect a
                # subject change immediately — don't perpetuate the stale flow.pid.
                pid_use, name_use = pid, name
            else:
                # Mid-flow flicker during confirm/challenge: keep the committed subject
                # to prevent a 1-frame blip from aborting an in-progress liveness check.
                pid_use, name_use = self.flow.pid, self.flow.name

            can_challenge = bool(self.require_blink and self.monitor is not None)
            events = self.monitor.events() if can_challenge else {}
            view = self.flow.step(True, pid_use, name_use, events,
                                  can_challenge=can_challenge, fail_open=self.dev_mode)
            return {
                "ok": True, "face": True, "name": name_use, "person_id": pid_use,
                "score": round(float(score), 3), "box": box, **view,
            }

    def capture_step(self, name: str, count: int = 6, max_seconds: float = 7.0,
                     require_live: bool = True) -> dict:
        """Capture one guided pose's worth of LIVE samples.

        Only real, live faces are stored — a printed/phone photo is rejected, so
        nobody can register using a photo. Frames are brightness-normalized before
        embedding for dark/bright robustness. The person is created only once we
        actually have a usable sample (no orphan empty records)."""
        embs: list[bytes] = []
        depths: list[float] = []
        last_emb = None
        live_fail = no_face = low_quality = 0
        start, _last = time.time(), 0.0
        while len(embs) < count and (time.time() - start) < max_seconds:
            frame = self.hub.frame()
            if frame is None:
                time.sleep(0.04)
                continue
            face = self._largest(frame)
            if face is None:
                no_face += 1
                time.sleep(0.04)
                continue
            if require_live and not self._enroll_live(frame, face):
                live_fail += 1
                time.sleep(0.05)
                continue
            if not self._good_quality(frame, face):     # drop blurry/badly-lit crops
                low_quality += 1
                time.sleep(0.05)
                continue
            emb = self.recognizer.embed(self._enhance(frame), face.raw)
            embs.append(self.recognizer.to_blob(emb))
            last_emb = emb
            if self.monitor is not None:                # record real-face depth for self-calibration
                d = self.monitor.snapshot()["depth"]
                if d > 0:
                    depths.append(d)
            time.sleep(0.12)   # spread captures over slightly different moments

        if not embs:
            spoof = live_fail > no_face
            if low_quality and low_quality >= max(no_face, live_fail):
                return {"ok": False, "captured": 0, "live_fail": live_fail,
                        "error": "image too blurry/dark — improve lighting and hold still"}
            return {"ok": False, "captured": 0, "live_fail": live_fail,
                    "spoof": spoof,
                    "error": ("real face not detected — use your real face, not a photo"
                              if spoof else "no face detected — face the camera and step closer")}

        # Block one face being enrolled under a second name (identity duplication).
        dup = duplicate_identity(self.recognizer, self.gallery, last_emb, name)
        if dup is not None:
            return {"ok": False, "captured": 0, "duplicate": True,
                    "error": f"this face is already registered as {dup[1]}"}

        existing = self.db.get_person_by_name(name)
        if existing:
            pid, created = existing["person_id"], False
        else:
            pid, created = self.db.add_person(name), True
        for blob in embs:
            self.db.add_face_template(pid, self.cipher.encrypt(blob))
        if depths:   # store this pose's median depth; DB keeps the running MAX (frontal pose)
            self.db.set_person_live_depth(pid, sorted(depths)[len(depths) // 2])
        self.reload_gallery()
        return {"ok": True, "captured": len(embs), "name": name, "person_id": pid,
                "existing": not created, "live_fail": live_fail}


class MeshOverlay:
    """Draws a live face mesh onto frames for the enrollment preview (the
    'computer-vision' look) from landmark pixel points supplied by the
    LivenessMonitor — so the heavy FaceLandmarker runs only once. Uses a Delaunay
    triangulation for the mesh lines (no legacy mediapipe.solutions API)."""

    MESH = (255, 224, 39)    # cyan (BGR)
    NODE = (166, 255, 61)    # green (BGR)

    def draw(self, frame, pts):
        import cv2
        if not pts:
            return frame
        h, w = frame.shape[:2]
        try:
            sub = cv2.Subdiv2D((0, 0, w, h))
            for (x, y) in pts:
                if 0 <= x < w and 0 <= y < h:
                    sub.insert((float(x), float(y)))
            for t in sub.getTriangleList():
                a, b, c = (int(t[0]), int(t[1])), (int(t[2]), int(t[3])), (int(t[4]), int(t[5]))
                if all(0 <= p[0] < w and 0 <= p[1] < h for p in (a, b, c)):
                    cv2.line(frame, a, b, self.MESH, 1, cv2.LINE_AA)
                    cv2.line(frame, b, c, self.MESH, 1, cv2.LINE_AA)
                    cv2.line(frame, c, a, self.MESH, 1, cv2.LINE_AA)
        except Exception:  # noqa: BLE001 - fall back to point cloud only
            pass
        for (x, y) in pts:
            cv2.circle(frame, (x, y), 1, self.NODE, -1, cv2.LINE_AA)
        return frame
