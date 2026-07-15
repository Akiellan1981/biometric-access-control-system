# Dual-Modal Biometric Access Control & Attendance System

Face **or** fingerprint identification on a Raspberry Pi 5, with anti-spoofing,
offline voice feedback, intruder capture, and a LAN dashboard. Runs fully offline.

> Design + budget + plan: see [`report/Project-Report.docx`](report/Project-Report.docx).

## The problem with most face-unlock systems

A plain face-recognition door only checks "does this face match a registered
template?" — so holding up a **photo or a video** of the registered person on a
phone screen is often enough to unlock it. Static-image checks alone don't prove
a live human is standing there.

## How this system defeats it

Every recognized face is handed a **live challenge** before access is granted —
`AccessFlow` (`acs/web/live.py`) picks **2 actions in random order** from
`{blink, turn head left, turn head right}` and the door only unlocks if a
`LivenessMonitor` background thread actually observes both, via MediaPipe
FaceMesh (blink = eye-aspect-ratio dip + recovery, turn = head-yaw threshold with
hysteresis) — a genuinely lightweight model, so it runs in real time on the Pi's
CPU with no GPU needed.

Why this beats a still photo *and* a replayed video:
- A **photo** cannot blink or turn on request — it fails instantly, every time.
- A **video** would need to already contain the *exact two actions the system just
  picked, in that order, at that moment* — since the sequence is randomized per
  attempt, a pre-recorded clip essentially never lines up, and there's no way to
  know the sequence in advance to prepare one.
- The challenge gates **every** recognized face unconditionally (not just
  low-confidence ones), so there's no bypass path.

This active challenge is the primary defense and is what's actually deployed.
There's also a secondary, passive per-frame layer in `core/liveness.py` (a
MiniFASNet ONNX ensemble when weights are present in `models/`, falling back to
MediaPipe depth-spread + blink on hardware without it) that adds a second signal
on top. **Honest limitation:** a very sophisticated real-time deepfake that could
react to the randomized prompts live would not be caught by either layer — closing
that gap fully needs a dedicated depth/IR sensor, which is a documented future
hardening step, not something claimed as solved here.

## Intruder capture — always local, never lost

Any denied attempt (unrecognized face, or a face that fails the live challenge)
triggers `IntruderCapture` (`acs/core/intruder.py`), which writes the frame to
**two copies on the device's own storage** (SD card / SSD) at the moment of
capture:
- a **dashboard copy** — viewable and, with the admin password, deletable from
  the web UI;
- a **protected archive copy** — no delete path in the code at all; it only ever
  disappears via the 31-day auto-purge.

Capture and storage happen entirely on-device and don't depend on the network in
any way — there's no "upload" step that can fail. The dashboard is a local web
app the Pi hosts itself; **any phone or laptop on the same Wi-Fi network** can
open `http://<pi-ip>:8010` at any time to view captured intruder photos, the live
feed, and logs. If Wi-Fi is down, nothing is lost or queued for later — the
photos were already saved locally the instant they were captured, and they're
simply not remotely viewable until connectivity (to the same LAN) is back.

## What's here

```
acs/
  config.py            config loader (reads config/config.yaml)
  types.py             Candidate / Detection / Method / Result
  storage/             SQLite (db.py, schema.sql), crypto.py, excel.py
  core/
    camera.py          picamera2 -> OpenCV webcam -> mock fallback
    face_detect.py     YuNet (FR-1.1)
    face_recognize.py  SFace embeddings + cosine match (FR-1.2)
    liveness.py        passive per-frame check: MiniFASNet ensemble, else
                       MediaPipe depth+blink fallback (FR-1.3, secondary signal)
    fingerprint/       base interface + mock + pyfingerprint (FR-2.x)
    decision.py        cooldown, logging, relay, voice, intruder (the consumer)
    intruder.py voice.py relay.py
  pipeline/            face_thread.py, finger_thread.py (producers)
  enroll.py            Register mode (face + finger -> one record)
  web/                 FastAPI + Jinja2 + HTMX dashboard
    live.py            AccessFlow + LivenessMonitor — the RANDOM 2-of-3
                       blink/turn-left/turn-right challenge (primary anti-spoof)
run.py                 Run mode entry point
config/config.yaml     every tunable
scripts/               download_models, render_voice, export_minifasnet_onnx, seed_demo
tests/                 hardware-free unit tests
```

## Quick start (development, on Windows/PC — no hardware needed)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

python scripts/seed_demo.py                      # sample data so the UI isn't empty
uvicorn acs.web.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000   (login: admin / admin)
```

`dev_mode: true` in `config/config.yaml` makes the pipeline use mocks and
fail-open liveness, so `python run.py` also works without a camera or sensor.

## On the Raspberry Pi

```bash
pip install -r requirements.txt -r requirements-pi.txt
python scripts/download_models.py                # YuNet + SFace
# add MiniFASNet ONNX to models/ (scripts/export_minifasnet_onnx.py)
python scripts/render_voice.py                   # the 3 voice clips

# set dev_mode: false and fingerprint.driver: pyfingerprint in config.yaml
python -m acs.enroll --name "Asha Khan"          # Register mode
python run.py --web                              # Run mode + dashboard
```

Autostart on boot: copy `systemd/access-control.service` to
`/etc/systemd/system/`, then `sudo systemctl enable --now access-control`.

## Tests

```bash
pip install pytest
pytest -q
```

Tests cover the hardware-free core: config, DB, decision logic (grant / cooldown /
spoof / unknown / finger-required), fingerprint mock, crypto, Excel export.

## Requirement mapping (spec → code)

| Spec | Where |
|------|-------|
| FR-1.x face + liveness | `core/face_detect.py`, `face_recognize.py`, `liveness.py` (passive), `web/live.py` (active random challenge), `pipeline/face_thread.py` |
| FR-2.x fingerprint | `core/fingerprint/` |
| FR-3.x decision/cooldown/FR-3.4 knob | `core/decision.py` |
| FR-4.x logging + Excel | `storage/db.py`, `storage/excel.py` |
| FR-5.x intruder capture | `core/intruder.py` |
| FR-6.x voice | `core/voice.py`, `scripts/render_voice.py` |
| FR-7.x dashboard + login | `web/` |
| §13 encryption | `storage/crypto.py` |

## Security notes
- Change the seeded `admin/admin` password from Settings immediately.
- Set a long random `web.session_secret` in `config.yaml`.
- Keep `dev_mode: false` in production so liveness fails closed.
