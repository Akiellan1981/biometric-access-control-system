"""Voice-guided liveness for a screenless door (pre-recorded clips).

Verifies ChallengeAnnouncer speaks the right clip on each NEW step, never
repeats an instruction on an unchanged poll, and announces terminal outcomes.
Pure logic — no audio device needed (Voice is a fake recorder)."""
from acs.core.voice import ChallengeAnnouncer


class FakeVoice:
    def __init__(self):
        self.played = []

    def play(self, key):
        self.played.append(key)


def _confirm(): return {"stage": "confirm"}
def _challenge(step, action): return {"stage": "challenge", "step": step, "action": action}
def _granted(): return {"stage": "granted"}
def _denied(): return {"stage": "denied_unknown"}
def _spoof(): return {"stage": "spoof"}
def _idle(): return {"stage": "idle"}


def test_full_spoken_sequence():
    v = FakeVoice()
    a = ChallengeAnnouncer(voice=v)
    # confirm -> blink -> turn_left -> granted, with repeated polls in between.
    # The announcer guides confirm+actions; the OUTCOME (granted) is silent here
    # because the DecisionEngine voices it (no double audio).
    a.update(_confirm()); a.update(_confirm())            # spoken once
    a.update(_challenge(0, "blink")); a.update(_challenge(0, "blink"))
    a.update(_challenge(1, "turn_left")); a.update(_challenge(1, "turn_left"))
    a.update(_granted()); a.update(_granted())
    assert v.played == ["confirm", "blink", "turn_left"]


def test_no_repeat_on_unchanged_poll():
    a = ChallengeAnnouncer()
    assert a.update(_challenge(0, "blink")) == "blink"
    assert a.update(_challenge(0, "blink")) is None        # same step -> silent


def test_outcomes_are_silent_decisionengine_owns_them():
    a = ChallengeAnnouncer()
    assert a.update(_granted()) is None
    assert a.update(_denied()) is None
    assert a.update(_spoof()) is None


def test_idle_resets_so_next_person_reannounced():
    v = FakeVoice()
    a = ChallengeAnnouncer(voice=v)
    a.update(_confirm())
    a.update(_idle())                                       # person leaves
    a.update(_confirm())                                    # next person -> spoken again
    assert v.played == ["confirm", "confirm"]


def test_ack_between_steps_when_enabled():
    v = FakeVoice()
    a = ChallengeAnnouncer(voice=v, ack=True)
    a.update(_challenge(0, "blink"))
    a.update(_challenge(1, "turn_right"))                   # completed step 0 -> "good" then next
    assert v.played == ["blink", "verify_ok", "turn_right"]
