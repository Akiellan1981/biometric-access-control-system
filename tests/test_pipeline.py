"""Deterministic AccessFlow tests (no camera).

Flow now: idle -(registered)-> challenge (2 random actions, NO 'is that you?' step)
-> granted | spoof; a spoof AUTO-RECOVERS after retry_hold so the page returns to
checking and the person can retry. idle -(unknown)-> denied_unknown.
"""
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acs.web.live import AccessFlow

BLINK_BASE = {"blink": 0, "turn_left": 0, "turn_right": 0}
BLINKED = {"blink": 1, "turn_left": 0, "turn_right": 0}


def make_flow(steps=1, gap=0.0, timeout=5.0, retry_hold=3.0):
    return AccessFlow(steps=steps, gap=gap, timeout=timeout, pool=["blink"],
                      retry_hold=retry_hold)


def check(label, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}")
    if not cond:
        raise AssertionError(f"FAILED: {label}")


def grant_A(flow):
    flow.step(True, 7, "Asha", BLINK_BASE)   # idle -> challenge (straight to actions)
    flow.step(True, 7, "Asha", BLINKED)      # action done -> granted


print("=== AccessFlow pipeline tests ===\n")

# 1: registered -> straight to challenge (no confirm) -> grant
print("Test 1: straight to challenge -> grant (no 'is that you')")
flow = make_flow()
v = flow.step(True, 7, "Asha", BLINK_BASE)
check("idle -> challenge directly", v["stage"] == "challenge")
check("no confirm stage ever", v["stage"] != "confirm")
v = flow.step(True, 7, "Asha", BLINKED)
check("action -> grant event", v["event"] == "grant" and v["stage"] == "granted")

# 2: granted A then stranger -> never inherits grant
print("\nTest 2: granted A -> stranger never granted")
flow = make_flow()
grant_A(flow)
check("setup granted", flow.state == "granted")
v = flow.step(True, None, None, BLINK_BASE)
check("stranger frame1: not granted", v["stage"] != "granted" and v.get("event") != "grant")
v = flow.step(True, None, None, BLINK_BASE)
check("stranger -> denied_unknown", v["stage"] == "denied_unknown")

# 3: granted A then registered B -> B re-challenged, not auto-granted
print("\nTest 3: granted A -> B must re-challenge")
flow = make_flow()
grant_A(flow)
v1 = flow.step(True, 8, "Bob", BLINK_BASE)
v2 = flow.step(True, 8, "Bob", BLINK_BASE)
check("B not granted on swap", v1["stage"] != "granted")
check("B enters challenge fresh", v2["stage"] == "challenge")

# 4: A lingers granted -> holds, no re-fire
print("\nTest 4: A lingers -> holds granted, single event")
flow = make_flow()
grant_A(flow)
v = flow.step(True, 7, "Asha", BLINK_BASE)
check("still granted", v["stage"] == "granted")
check("no duplicate event", v["event"] is None)

# 5: unknown performing actions never granted
print("\nTest 5: unknown actions -> never granted")
flow = make_flow()
ev = dict(BLINK_BASE)
for i in range(4):
    ev = {"blink": ev["blink"] + 1, "turn_left": ev["turn_left"] + 1, "turn_right": 0}
    v = flow.step(True, None, None, ev)
    check(f"unknown {i}: not granted", v["stage"] != "granted" and v.get("event") != "grant")

# 6: SPOOF AUTO-RECOVERS -> back to checking, not stuck
print("\nTest 6: spoof auto-recovers to checking (the stuck bug)")
flow = make_flow(steps=1, gap=0.0, timeout=0.0, retry_hold=0.0)
flow.step(True, 7, "Asha", BLINK_BASE)        # -> challenge
time.sleep(0.02)
v = flow.step(True, 7, "Asha", BLINK_BASE)    # no action + timeout 0 -> spoof
check("spoofed", v["stage"] == "spoof" and v["event"] == "spoof")
time.sleep(0.02)
v = flow.step(True, 7, "Asha", BLINK_BASE)    # retry_hold elapsed -> recovers
check("recovered: not stuck on spoof", v["stage"] != "spoof")
check("recovered into challenge (checking)", v["stage"] == "challenge")

# 7: face leaves -> idle
print("\nTest 7: face leaves -> idle")
flow = make_flow()
grant_A(flow)
v = flow.step(False, None, None, {})
check("idle on no face", v["stage"] == "idle" and v["event"] is None)

# 8: no liveness backend -> prod fails CLOSED, dev fails open (no confirm step)
print("\nTest 8: no backend -> prod spoof, dev grant (immediate)")
flow = make_flow()
v = flow.step(True, 7, "Asha", {}, can_challenge=False, fail_open=False)
check("prod no-backend: spoof immediately", v["stage"] == "spoof")
flow = make_flow()
v = flow.step(True, 7, "Asha", {}, can_challenge=False, fail_open=True)
check("dev no-backend: grant immediately", v["stage"] == "granted" and v["event"] == "grant")

# 9: guards
print("\nTest 9: AccessFlow guards")
try:
    AccessFlow(pool=[])
    raise AssertionError("empty pool should raise")
except ValueError:
    check("empty pool raises", True)
f = AccessFlow(steps=1, gap=0.0, timeout=5.0, pool=["blink", "wink"])
f.step(True, 7, "Asha", BLINK_BASE)           # -> challenge
v = f.step(True, 7, "Asha", BLINK_BASE)
check("unknown label view ok", "seq" in v)

# 10: access expires after grant_hold -> must re-verify
print("\nTest 10: granted expires -> re-verify")
flow = make_flow()
flow.grant_hold = 0.0
grant_A(flow)
check("granted", flow.state == "granted")
time.sleep(0.02)
v = flow.step(True, 7, "Asha", BLINK_BASE)    # grant_hold elapsed
check("re-locked into challenge (re-verify)", v["stage"] == "challenge")

print("\n=== ALL PIPELINE TESTS PASSED ===")
