"""Offline voice feedback — plays pre-rendered WAV clips (spec FR-6).

Runtime only PLAYS audio (no synthesis). Generate the clips once with
scripts/render_voice.py. Playback is non-blocking and degrades to a log line
if the clip or an audio backend is missing.
"""
from __future__ import annotations

import logging
import platform
import subprocess
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_AUDIO_LOCK = threading.Lock()   # serialize playback so prompts never talk over each other


class Voice:
    """Plays pre-recorded WAV clips, per language. Clips live in language
    subfolders: voice_assets/<lang>/<file>.wav (en | ta | hi). The active
    language is a runtime setting (DB key 'voice_lang') so the dashboard can
    switch it live and BOTH the dashboard and the door pipeline pick it up."""

    LANGS = {"en": "English", "ta": "Tamil", "hi": "Hindi"}

    def __init__(self, cfg, db=None):
        self.enabled = bool(cfg.get("voice.enabled", True))
        self.base = Path(cfg.path("paths.voice"))
        self.clips = cfg.get("voice.clips", {}) or {}      # key -> filename
        self.default_lang = str(cfg.get("voice.language", "en"))
        self.db = db

    def language(self) -> str:
        """Current language code, from the DB setting if available."""
        if self.db is not None:
            try:
                v = self.db.get_setting("voice_lang", None)
                if v in self.LANGS:
                    return v
            except Exception:  # noqa: BLE001 - never let audio config break the door
                pass
        return self.default_lang if self.default_lang in self.LANGS else "en"

    def set_language(self, lang: str) -> bool:
        """Switch language at runtime (persisted). Returns False if unknown."""
        if lang not in self.LANGS:
            return False
        if self.db is not None:
            self.db.set_setting("voice_lang", lang)
        else:
            self.default_lang = lang
        return True

    def _resolve(self, key: str) -> Path | None:
        fname = self.clips.get(key, f"{key}.wav")
        lang = self.language()
        # current language, then English, then a flat clip — first that exists wins.
        for cand in (self.base / lang / fname, self.base / "en" / fname, self.base / fname):
            if cand.exists():
                return cand
        return None

    def play(self, key: str):
        if not self.enabled:
            return
        clip = self._resolve(key)
        if clip is None:
            log.info("[voice] (no clip) %s [%s]", key, self.language())
            return
        threading.Thread(target=self._play, args=(clip,), daemon=True).start()

    @staticmethod
    def _play(clip: Path):
        # one clip at a time — overlapping aplay/winsound calls garble the prompt
        with _AUDIO_LOCK:
            try:
                if platform.system() == "Windows":
                    import winsound
                    winsound.PlaySound(str(clip), winsound.SND_FILENAME)
                else:
                    subprocess.run(["aplay", "-q", str(clip)], check=False)
            except Exception as e:  # noqa: BLE001
                log.warning("voice playback failed: %s", e)


class ChallengeAnnouncer:
    """Speaks the access flow to a SCREENLESS door via pre-recorded clips.

    Feed it the view dict from AccessFlow.step() every tick. It returns the clip
    key to play on each NEW state/step (and plays it if a Voice was supplied),
    or None when nothing changed — so an instruction is spoken once, not repeated
    on every poll. Lets a person be guided by voice instead of a screen, which
    also suits low-literacy users better than on-screen text.

    Scope is the CHALLENGE GUIDANCE only (confirm + blink/turn prompts). The
    terminal outcomes (granted / denied / spoof) are voiced by the DecisionEngine,
    so the announcer stays silent on them to avoid double audio.
    """

    # AccessFlow stage  ->  Voice clip key (guidance only; outcomes are the
    # DecisionEngine's job). Challenge steps map via the raw 'action' key.
    _STAGE_CLIP = {"confirm": "confirm"}

    def __init__(self, voice=None, ack: bool = False):
        self.voice = voice
        self.ack = ack            # play a short "good" between completed steps
        self._last = None         # (stage, step) already announced

    def reset(self):
        self._last = None

    def update(self, view: dict) -> str | None:
        stage = view.get("stage")
        if not stage or stage == "idle":
            self._last = None
            return None
        sig = (stage, view.get("step"))
        if sig == self._last:
            return None
        prev = self._last
        self._last = sig

        if stage == "challenge":
            # acknowledge a just-completed step before the next instruction
            if (self.ack and prev is not None and prev[0] == "challenge"
                    and prev[1] is not None and view.get("step", 0) > prev[1]):
                self._say("verify_ok")
            key = view.get("action")            # raw blink/turn_left/turn_right
        else:
            key = self._STAGE_CLIP.get(stage)
        if key:
            self._say(key)
        return key

    def _say(self, key: str):
        if self.voice is not None:
            self.voice.play(key)
