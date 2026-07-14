# Dual-Modal Biometric Access Control & Attendance System

Face **or** fingerprint identification on a Raspberry Pi 5, with anti-spoofing,
offline voice feedback, intruder capture, and a LAN dashboard. Runs fully offline.

> Design + budget + plan: see [`report/Project-Report.docx`](report/Project-Report.docx).

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
    liveness.py        MiniFASNet ensemble + MediaPipe blink (FR-1.3)
    fingerprint/       base interface + mock + pyfingerprint (FR-2.x)
    decision.py        cooldown, logging, relay, voice, intruder (the consumer)
    intruder.py voice.py relay.py
  pipeline/            face_thread.py, finger_thread.py (producers)
  enroll.py            Register mode (face + finger -> one record)
  web/                 FastAPI + Jinja2 + HTMX dashboard
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
| FR-1.x face + liveness | `core/face_detect.py`, `face_recognize.py`, `liveness.py`, `pipeline/face_thread.py` |
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
