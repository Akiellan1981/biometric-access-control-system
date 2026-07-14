# Raspberry Pi 5 — Full Deployment Guide

Wiring, libraries, Wi-Fi, configuration, running, and diagnostics for the Dual-Modal
Biometric Access Control system. The Pi code is already in the repo (`run.py` +
`acs/core/{camera,motion,relay,indicators,voice,fingerprint}.py`); this guide tells you
how to wire, configure, and operate it.

---

## 1. Bill of materials

| Part | Notes |
|------|------|
| Raspberry Pi 5 (4/8 GB) + **active cooler** | ML load throttles a bare Pi 5 — cooler is required |
| Pi Camera Module 3 (CSI) | recognition + liveness |
| PIR motion sensor (HC-SR501) | wake on approach |
| Relay module (1-ch, 5 V) **or** MOSFET | drives the door strike/lock |
| Door strike/lock + **its own 12 V PSU** | NEVER power the strike from the Pi |
| Status LED + 330 Ω resistor | "camera live" cue |
| Lamp/IR illuminator + relay/MOSFET (+ own PSU) | low-light fill |
| R503 (or R307) fingerprint sensor (UART) | second factor |
| **USB sound card + small speaker** (or I²S MAX98357A) | voice prompts — **Pi 5 has no 3.5 mm jack** |
| SSD (≈32 GB) USB/NVMe | code, DB, models, photos |

---

## 2. Pin map (BCM numbering)

These match the defaults in `config/config.yaml`. Change config if you wire differently.

| Function | BCM (config key) | Physical pin | Wiring |
|----------|------------------|--------------|--------|
| PIR OUT | **GPIO4** (`motion.pin`) | 7 | OUT→pin7, VCC→5 V (pin2), GND→GND (pin6) |
| Relay IN (door) | **GPIO17** (`relay.gpio_pin`) | 11 | IN→pin11, VCC→5 V, GND→GND; strike on COM/NO + 12 V PSU |
| Status LED | **GPIO23** (`status_led.pin`) | 16 | pin16 → 330 Ω → LED(+), LED(−)→GND |
| Lamp control | **GPIO24** (`lamp.pin`) | 18 | pin18 → relay/MOSFET → lamp (+ own PSU) |
| Fingerprint TX→Pi RX | **GPIO15 (RXD)** | 10 | sensor **TX** → Pi pin10 |
| Fingerprint RX←Pi TX | **GPIO14 (TXD)** | 8 | sensor **RX** → Pi pin8 |
| Fingerprint power | 3.3 V + GND | 1 + 9 | R503 = 3.3 V logic; verify your R307 module is 3.3 V logic |
| Camera | CSI ribbon | — | Pi 5 MIPI cam port (not a GPIO) |
| Speaker | USB sound card | USB | simplest; avoids GPIO. (I²S amp: GPIO18/19/21 if you prefer) |

**No pin conflicts** among the above. **Power rules:** the door strike and any real lamp
get their **own supply** through the relay/MOSFET — a GPIO sources only ~16 mA (fine for the
status LED via its resistor, not for a lock or lamp). Use a relay module with a flyback diode
for inductive loads.

---

## 3. OS preparation

```bash
# Raspberry Pi OS Bookworm 64-bit
sudo apt update && sudo apt full-upgrade -y
sudo raspi-config
#   Interface Options → Serial Port:  login shell over serial = NO,  serial hardware = YES
#   (Camera is auto-enabled on Bookworm.)
sudo reboot
```
Confirm `enable_uart=1` is in `/boot/firmware/config.txt`. Add your user to hardware groups:
```bash
sudo usermod -aG dialout,gpio,video,audio $USER   # then log out/in
```

---

## 4. Install

```bash
sudo apt install -y git python3-venv python3-picamera2 python3-libcamera \
                    libcamera-apps libportaudio2 alsa-utils

git clone <your-repo> ~/Biometric-Access-Control-System
cd ~/Biometric-Access-Control-System

# venv MUST see the apt-installed picamera2:
python3 -m venv --system-site-packages .venv
source .venv/bin/activate

pip install -r requirements.txt -r requirements-pi.txt
python scripts/download_models.py        # YuNet + SFace + face_landmarker.task
python scripts/render_voice.py           # EN clips; TA/HI need a Piper voice or your own WAVs
```
> **Pi 5 GPIO:** `gpiozero` uses the **lgpio** backend on the Pi 5 (installed above). If you
> hit "Cannot determine SOC peripheral base", run with `export GPIOZERO_PIN_FACTORY=lgpio`.

---

## 5. Wi-Fi

Bookworm uses NetworkManager:
```bash
nmcli device wifi list
sudo nmcli device wifi connect "YOUR_SSID" password "YOUR_PASSWORD"
hostname -I                                  # the Pi's LAN IP — use this in a browser
```
Recommended **static IP** so the dashboard URL is stable:
```bash
sudo nmcli con mod "YOUR_SSID" ipv4.addresses 192.168.1.50/24 ipv4.gateway 192.168.1.1 \
                               ipv4.dns 8.8.8.8 ipv4.method manual
sudo nmcli con up "YOUR_SSID"
```
The viewing laptop/phone must be on the **same Wi-Fi/subnet** to see the live feed and logs.

---

## 6. Production configuration (`config/config.yaml`)

```yaml
dev_mode: false                 # CRITICAL: fail-closed liveness on the door
camera: { source: auto }        # picks picamera2 on the Pi
motion:     { enabled: true, driver: gpio, pin: 4, idle_off_seconds: 60 }
relay:      { enabled: true, gpio_pin: 17, active_high: true, hold_seconds: 3 }
status_led: { enabled: true, driver: gpio, pin: 23 }
lamp:       { enabled: true, driver: gpio, pin: 24, dark_threshold: 60 }
fingerprint:{ driver: pyfingerprint, port: /dev/serial0, baudrate: 57600 }
web:        { host: 0.0.0.0, port: 8010 }
voice:      { enabled: true, language: en }
```
- **Relay polarity:** many relay boards are **active-LOW** — if the lock fires inverted, set
  `relay.active_high: false`.
- `web.session_secret` left as the placeholder is auto-replaced by a random secret
  (`data/session.key`); set your own to silence the preflight warning.
- **First dashboard login forces a password change** — do it.
- **Mount data on the SSD:** run the project from the SSD, or symlink `data/` to the SSD so
  the DB (`data/access.db`), encrypted photos, and the key (`data/secret.key`) live there.
  **Back up `data/secret.key`** — without it, stored templates/photos can't be decrypted.

---

## 7. Run

Manual:
```bash
source .venv/bin/activate
python run.py --web            # device pipeline + dashboard (http://<pi-ip>:8010)
```
As a service (auto-start, auto-restart) — edit paths/User in `systemd/access-control.service`:
```bash
sudo cp systemd/access-control.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now access-control
journalctl -u access-control -f          # live logs
```

---

## 8. Enrolling people

From a laptop/phone on the same Wi-Fi: `http://<pi-ip>:8010` → log in → **change the
password** → **Try → Register mode** → type the name → **Start** → follow the on-screen poses
(front/left/right/up/down). One face can't be registered under two names; re-using the same
name just adds more photos. (Voice-guided headless registration is the next build phase;
today enrollment uses the dashboard preview.)

---

## 9. How it works at the door

PIR senses approach → camera wakes (**status LED on**) → if dark, **lamp on** → voice
*"welcome…"* → YuNet+SFace recognise → voice *"confirming entry"* → MediaPipe asks **2 random
actions** (blink / turn left / right), spoken → on success **"access granted"** + relay
unlocks + logged; on failure **"movement not detected, try again"** + photo saved. A
fingerprint touch grants in parallel. Idle → camera sleeps (timer set on the dashboard),
**LED off**.

---

## 10. Diagnostics (run each to isolate a fault)

| Subsystem | Command | Healthy result |
|-----------|---------|----------------|
| Camera | `rpicam-hello -t 2000` | live preview window/stream |
| Camera (py) | `python -c "from picamera2 import Picamera2;c=Picamera2();c.start();print('ok')"` | prints ok |
| GPIO/LED | `python -c "from gpiozero import LED;import time;l=LED(23);l.on();time.sleep(2);l.off()"` | LED lights 2 s |
| Relay | same as LED on pin 17 | audible click (lock actuates) |
| PIR | `python -c "from gpiozero import MotionSensor as M;m=M(4);print('wave');m.wait_for_motion(timeout=10);print('motion')"` | prints motion on wave |
| Audio devices | `aplay -l` | your USB/I²S card listed |
| Audio play | `aplay voice_assets/en/welcome.wav` | hear the clip |
| Serial | `ls -l /dev/serial0` | symlink exists |
| Fingerprint | `python -c "from pyfingerprint.pyfingerprint import PyFingerprint as P;print(P('/dev/serial0',57600,0xFFFFFFFF,0).verifyPassword())"` | `True` |
| Database | `sqlite3 data/access.db "SELECT * FROM events ORDER BY ts DESC LIMIT 5;"` | recent rows |
| Models | `ls models/` | 3 files present |
| Native HW errors | `ACS_QUIET_NATIVE=0 python run.py` | shows picamera2/gpiozero stderr (normally silenced) |

### Common failures
| Symptom | Cause → fix |
|---------|-------------|
| No sound | Pi 5 has no jack → use a USB sound card; set it as ALSA default (`/etc/asound.conf`) |
| gpiozero "SOC peripheral base" error | Pi 5 → `pip install lgpio`; `export GPIOZERO_PIN_FACTORY=lgpio` |
| `picamera2` not found in venv | recreate venv with `--system-site-packages` |
| Permission denied on `/dev/serial0` | `sudo usermod -aG dialout $USER`; reboot |
| Lock never opens | relay `active_high` inverted, or `relay.enabled:false`, or `fingerprint_required_for_unlock:true` |
| **Everyone denied as spoof** | `dev_mode:false` + missing `models/face_landmarker.task` (fail-closed) → run `download_models.py` |
| Nobody recognised | empty gallery → enroll people; or re-enroll after lighting changes |
| Dashboard unreachable | `web.host` must be `0.0.0.0`; same subnet; correct IP from `hostname -I` |
| Voice says wrong/no language | Tamil/Hindi WAVs not rendered → record into `voice_assets/ta|hi/` |

---

## 11. The database ("DB codes")

- Engine: **SQLite** at `data/access.db` (code: `acs/storage/db.py`, schema `acs/storage/schema.sql`).
- Tables: `people`, `face_templates` (encrypted 128-D), `finger_templates`, `events` (the entry
  log), `users` (dashboard), `settings` (runtime: voice language, sleep timer, password-changed flag).
- Retention: events + intruder photos older than `intruder.retention_days` (30) are purged at
  startup and hourly. Entry graph reads `entries_by_day(30)`.
- **Backup:** copy the whole `data/` directory (DB + `secret.key` + `session.key` + photos).
  Keep `secret.key` safe and private — it decrypts every template and photo.
```
