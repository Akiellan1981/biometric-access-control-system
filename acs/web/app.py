"""FastAPI LAN dashboard (spec FR-7): logs, intruder gallery, people, export, login.

Server-rendered with Jinja2 + HTMX (no JS framework). Runs on Windows for
development against the SQLite DB; the camera stream only works on the device.

    uvicorn acs.web.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import io
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from acs.config import Config
from acs.storage.db import DB
from acs.storage.excel import export_events
from acs.web.auth import (hash_password, load_or_create_secret, make_token,
                          read_token, verify_password)

cfg = Config.load()
db = DB(cfg.path("paths.db"))
db.init_schema()

# seed admin if the users table is empty
if not db.has_users():
    db.upsert_user(cfg.get("web.admin_user", "admin"),
                   hash_password(cfg.get("web.default_password", "admin")))

# Dashboard-only deployments (serve.py with no device pipeline) still enforce the
# retention window so the events log / images don't grow past it.
try:
    for _img in db.purge_events(int(cfg.get("intruder.retention_days", 30))):
        try:
            (Path(cfg.path("paths.unauthorized")) / Path(_img).name).unlink()
        except OSError:
            pass
except Exception:  # noqa: BLE001 - never block startup on housekeeping
    pass

from acs.storage.crypto import TemplateCipher  # noqa: E402
cipher = TemplateCipher(cfg.path("paths.key_file"))

# Shared camera + face engine for the live 'Try' page (built lazily on first use
# so importing the app never opens the webcam).
_hub = None
_engine = None
_decider = None
_mesh = None


def get_mesh_overlay():
    global _mesh
    if _mesh is None:
        from acs.web.live import MeshOverlay
        _mesh = MeshOverlay()
    return _mesh


def get_hub():
    global _hub
    if _hub is None:
        from acs.web.live import CameraHub
        _hub = CameraHub(cfg, db)
    _hub.start()
    return _hub


def get_engine():
    global _engine
    if _engine is None:
        from acs.web.live import FaceEngine
        _engine = FaceEngine(cfg, db, cipher, get_hub())
    return _engine


def get_decider():
    global _decider
    if _decider is None:
        from acs.core.decision import DecisionEngine
        from acs.core.intruder import IntruderCapture
        from acs.core.voice import Voice
        _decider = DecisionEngine(db, cfg, voice=Voice(cfg, db), relay=None,
                                  intruder=IntruderCapture(cfg, cipher))
    return _decider

SECRET = load_or_create_secret(
    Path(cfg.path("paths.key_file")).parent / "session.key",
    cfg.get("web.session_secret"))
SESSION_HOURS = cfg.get("web.session_hours", 8)
COOKIE = "acs_session"

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Access Control Dashboard")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


class _ForcePasswordChange:
    """Pure-ASGI middleware: until the default admin password is changed once, a
    logged-in user is redirected to Settings for any other page. Implemented at the
    ASGI level (not BaseHTTPMiddleware) so it never wraps the long-lived MJPEG
    /camera/stream response — which otherwise logs spurious CancelledError tracebacks
    on client disconnect."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path", "")
            allowed = (path.startswith("/static") or path.startswith("/settings")
                       or path.startswith("/network")
                       or path in ("/login", "/logout", "/healthz"))
            if not allowed:
                token = Request(scope).cookies.get(COOKIE, "")
                if read_token(token, SECRET):
                    try:
                        changed = db.get_setting("pw_changed", "0") == "1"
                    except Exception:  # noqa: BLE001 - never lock the admin out on a DB hiccup
                        changed = True
                    if not changed:
                        resp = RedirectResponse(
                            "/settings?msg=Please+change+the+default+password+to+continue",
                            status_code=302)
                        await resp(scope, receive, send)
                        return
        await self.app(scope, receive, send)


app.add_middleware(_ForcePasswordChange)


# ---------------- auth plumbing ----------------
def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    user = read_token(token, SECRET)
    if not user:
        raise HTTPException(status_code=401)
    return user


@app.exception_handler(401)
async def _login_redirect(request: Request, exc):
    return RedirectResponse("/login", status_code=302)


@app.get("/healthz")
def healthz():
    """Unauthenticated liveness probe for monitoring (is the dashboard process up,
    is the DB reachable). Lets you alert if the door controller goes dark."""
    try:
        db.get_setting("pw_changed", "0")
        return {"ok": True}
    except Exception:  # noqa: BLE001
        return Response('{"ok": false}', media_type="application/json", status_code=503)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    row = db.get_user(username)
    if not row or not verify_password(password, row["pw_hash"]):
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "Invalid credentials"}, status_code=401)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(COOKIE, make_token(username, SECRET, SESSION_HOURS),
                    httponly=True, samesite="lax", max_age=SESSION_HOURS * 3600)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


# ---------------- pages ----------------
def _ctx(request, user, **extra):
    return {"request": request, "user": user, **extra}


@app.get("/", response_class=HTMLResponse)
def overview(request: Request, user: str = Depends(current_user)):
    days = db.entries_by_day(30)
    maxc = max([c for _, c in days], default=0)
    chart = [{"date": d, "count": c,
              "pct": int(round(c * 100 / maxc)) if maxc else 0} for d, c in days]
    return templates.TemplateResponse("overview.html", _ctx(
        request, user,
        stats=db.stats_today(),
        recent=db.recent_events(8),
        intruders=db.intruders(8),
        chart=chart, chart_max=maxc,
    ))


@app.get("/logs", response_class=HTMLResponse)
def logs(request: Request, user: str = Depends(current_user)):
    return templates.TemplateResponse("logs.html", _ctx(
        request, user, rows=db.query_events(limit=200)))


@app.get("/logs/table", response_class=HTMLResponse)
def logs_table(request: Request, user: str = Depends(current_user),
               name: str = "", date: str = "", method: str = "", result: str = ""):
    rows = db.query_events(name=name or None, date=date or None,
                           method=method or None, result=result or None, limit=200)
    return templates.TemplateResponse("_logs_table.html", {"request": request, "rows": rows})


@app.get("/intruders", response_class=HTMLResponse)
def intruders(request: Request, user: str = Depends(current_user), msg: str = ""):
    return templates.TemplateResponse("intruders.html", _ctx(
        request, user, rows=db.intruders(200), msg=msg))


@app.get("/people", response_class=HTMLResponse)
def people(request: Request, user: str = Depends(current_user)):
    return templates.TemplateResponse("people.html", _ctx(
        request, user, people=db.list_people()))


@app.post("/people/enroll")
def people_enroll(user: str = Depends(current_user), name: str = Form(...)):
    db.get_or_create_person(name.strip())   # never create a duplicate of the same name
    return RedirectResponse("/people", status_code=302)


@app.post("/people/{pid}/rename")
def people_rename(pid: int, user: str = Depends(current_user), name: str = Form(...)):
    db.rename_person(pid, name.strip())
    return RedirectResponse("/people", status_code=302)


@app.post("/people/{pid}/delete")
def people_delete(pid: int, user: str = Depends(current_user)):
    db.delete_person(pid)
    return RedirectResponse("/people", status_code=302)


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request, user: str = Depends(current_user), msg: str = ""):
    keys = ["dev_mode", "decision.cooldown_seconds", "decision.fingerprint_required_for_unlock",
            "face.recognition_cosine_thr", "liveness.live_score_thr", "intruder.retention_days"]
    shown = {k: cfg.get(k) for k in keys}
    voice = get_decider().voice
    idle_off = db.get_setting("idle_off_seconds", cfg.get("motion.idle_off_seconds", 60))
    grant_hold = db.get_setting("grant_hold_seconds", cfg.get("decision.grant_hold_seconds", 5))
    spoof_timeout = db.get_setting("challenge_timeout_seconds",
                                   cfg.get("liveness.challenge_timeout_seconds", 10))
    camera_source = db.get_setting("camera_source", cfg.get("camera.source", "auto"))
    return templates.TemplateResponse("settings.html", _ctx(
        request, user, shown=shown, msg=msg,
        languages=voice.LANGS, current_lang=voice.language(),
        idle_off=idle_off, grant_hold=grant_hold, spoof_timeout=spoof_timeout,
        camera_source=camera_source,
        pw_changed=(db.get_setting("pw_changed", "0") == "1")))


@app.post("/settings/camera")
def set_camera(user: str = Depends(current_user), source: str = Form(...)):
    """Toggle the camera between the PC webcam and the Raspberry Pi camera."""
    global _hub
    if source not in ("auto", "opencv", "picamera2", "mock"):
        return RedirectResponse("/settings?msg=Unknown+camera+source", status_code=302)
    db.set_setting("camera_source", source)
    if _hub is not None:                 # reopen with the new source on next use
        try:
            _hub.stop()
        except Exception:  # noqa: BLE001
            pass
    label = {"opencv": "PC webcam", "picamera2": "Raspberry Pi camera",
             "auto": "auto", "mock": "mock"}[source]
    return RedirectResponse(f"/settings?msg=Camera+set+to+{label}", status_code=302)


_wifi = None


def get_wifi():
    global _wifi
    if _wifi is None:
        from acs.core.wifi import WifiManager
        _wifi = WifiManager()
    return _wifi


@app.get("/network", response_class=HTMLResponse)
def network_page(request: Request, user: str = Depends(current_user),
                 msg: str = "", scan: int = 0):
    w = get_wifi()
    nets = w.scan() if scan else []     # scan only on demand (nmcli rescan is slow)
    return templates.TemplateResponse("network.html", _ctx(
        request, user, status=w.status(), nets=nets, did_scan=bool(scan),
        port=cfg.get("web.port", 8010), msg=msg))


@app.post("/network/connect")
def network_connect(user: str = Depends(current_user),
                    ssid: str = Form(...), password: str = Form("")):
    from urllib.parse import quote
    ok, m = get_wifi().connect(ssid, password)
    return RedirectResponse(f"/network?msg={quote(m)}", status_code=302)


@app.post("/settings/runtime")
def set_runtime(user: str = Depends(current_user), idle_off: int = Form(...),
                grant_hold: int = Form(...), spoof_timeout: int = Form(...)):
    """Live-editable timers: camera sleep + access-hold + spoof timeout (max 30s)."""
    db.set_setting("idle_off_seconds", max(5, min(int(idle_off), 3600)))
    db.set_setting("grant_hold_seconds", max(2, min(int(grant_hold), 300)))
    db.set_setting("challenge_timeout_seconds", max(3, min(int(spoof_timeout), 30)))  # cap 30s
    return RedirectResponse("/settings?msg=Timers+updated", status_code=302)


@app.post("/settings/language")
def set_language(user: str = Depends(current_user), lang: str = Form(...)):
    """Switch the door's voice language at runtime and CONFIRM it by speaking
    '<language> selected' in the newly-chosen language on the door speaker."""
    voice = get_decider().voice
    if voice.set_language(lang):
        voice.play("language_selected")     # spoken in the new language (test-ok audio)
        return RedirectResponse(
            f"/settings?msg=Voice+language+set+to+{voice.LANGS.get(lang, lang)}", status_code=302)
    return RedirectResponse("/settings?msg=Unknown+language", status_code=302)


@app.get("/status", response_class=HTMLResponse)
def status_page(request: Request, user: str = Depends(current_user)):
    from acs.core.preflight import production_warnings
    from acs.core.selfcheck import system_status
    voice = get_decider().voice
    checks = system_status(cfg, db, getattr(cipher, "enabled", False), voice.language())
    warnings = production_warnings(cfg, getattr(cipher, "enabled", False))
    info = {
        "dev_mode": cfg.get("dev_mode"),
        "web.host": cfg.get("web.host"),
        "relay.enabled": cfg.get("relay.enabled"),
        "motion.enabled": cfg.get("motion.enabled"),
        "status_led.enabled": cfg.get("status_led.enabled"),
        "lamp.enabled": cfg.get("lamp.enabled"),
        "voice.language": voice.language(),
    }
    return templates.TemplateResponse("status.html", _ctx(
        request, user, checks=checks, warnings=warnings, info=info))


@app.get("/status/camera-test")
def status_camera_test(user: str = Depends(current_user)):
    """Live probe: open the camera, grab a frame, run one recognition pass.
    This is the real 'is the camera + recognition working' test."""
    try:
        eng = get_engine()
        if not eng.available:
            return {"ok": False, "error": eng.error or "face engine unavailable"}
        frame = get_hub().frame()
        if frame is None:
            return {"ok": False, "error": "no camera frame (camera not producing images)"}
        rec = eng.recognize(frame)
        return {"ok": True, "camera": True, "engine": True,
                "liveness_monitor": eng.monitor is not None,
                "face_detected": bool(rec.get("face")),
                "stage": rec.get("stage"), "name": rec.get("name")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.post("/settings/password")
def change_password(user: str = Depends(current_user),
                    current: str = Form(...), new: str = Form(...)):
    row = db.get_user(user)
    if not row or not verify_password(current, row["pw_hash"]):
        return RedirectResponse("/settings?msg=Wrong+current+password", status_code=302)
    db.upsert_user(user, hash_password(new))
    db.set_setting("pw_changed", "1")     # clears the forced first-login change
    return RedirectResponse("/settings?msg=Password+updated", status_code=302)


@app.get("/export")
def export(user: str = Depends(current_user)):
    rows = db.query_events(limit=100000)
    buf = io.BytesIO()
    tmp = cfg.base_dir / "data" / "attendance_export.xlsx"
    export_events(rows, tmp)
    buf.write(Path(tmp).read_bytes())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=attendance.xlsx"})


@app.get("/media/unauthorized/{fname}")
def media(fname: str, user: str = Depends(current_user)):
    safe = Path(fname).name
    path = Path(cfg.path("paths.unauthorized")) / safe
    if not path.exists():
        raise HTTPException(404)
    data = path.read_bytes()
    if safe.endswith(".enc"):               # decrypt encrypted intruder images
        try:
            data = cipher.decrypt(data)
        except Exception:
            raise HTTPException(500, "cannot decrypt image")
    return Response(content=data, media_type="image/jpeg")


def _admin_ok(user: str, password: str) -> bool:
    row = db.get_user(user)
    return bool(row and verify_password(password, row["pw_hash"]))


def _delete_dashboard_copies(rows):
    """Delete the dashboard image + its event row. NEVER touches the protected
    archive (paths.archive) — that copy only auto-deletes at the retention limit."""
    base = Path(cfg.path("paths.unauthorized"))
    n = 0
    for row in rows:
        if not row:
            continue
        if row["image_path"]:
            try:
                (base / Path(row["image_path"]).name).unlink()
            except OSError:
                pass
        db.delete_event(row["id"])
        n += 1
    return n


@app.post("/intruders/delete")
def intruders_delete(user: str = Depends(current_user),
                     password: str = Form(...), ids: list[int] = Form(default=[])):
    """Delete selected intruder images from the DASHBOARD (admin password required).
    Works for one (single checkbox) or many. Archive on the card is untouched."""
    if not _admin_ok(user, password):
        return RedirectResponse("/intruders?msg=Wrong+admin+password", status_code=302)
    n = _delete_dashboard_copies([db.get_event(i) for i in ids])
    return RedirectResponse(f"/intruders?msg=Deleted+{n}+image(s)+from+dashboard",
                            status_code=302)


@app.post("/intruders/delete-all")
def intruders_delete_all(user: str = Depends(current_user), password: str = Form(...)):
    """Delete the WHOLE dashboard intruder gallery (admin password required).
    The protected memory-card archive is kept (auto-deletes at 31 days)."""
    if not _admin_ok(user, password):
        return RedirectResponse("/intruders?msg=Wrong+admin+password", status_code=302)
    n = _delete_dashboard_copies(db.intruders(100000))
    return RedirectResponse(f"/intruders?msg=Deleted+all+{n}+from+dashboard+(archive+kept)",
                            status_code=302)


@app.get("/try", response_class=HTMLResponse)
def try_page(request: Request, user: str = Depends(current_user)):
    eng = get_engine()
    return templates.TemplateResponse("try.html", _ctx(
        request, user, available=eng.available, error=eng.error))


@app.post("/try/register/step")
def try_register_step(user: str = Depends(current_user),
                      name: str = Form(...), count: int = Form(6), pose: str = Form("")):
    """Capture one guided pose. Real/live faces only — photos are rejected."""
    eng = get_engine()
    if not eng.available:
        return {"ok": False, "error": "face models unavailable — see Settings/README"}
    name = name.strip()
    if not name:
        return {"ok": False, "error": "enter a name first"}
    return eng.capture_step(name, count=max(1, min(count, 12)))


@app.post("/try/enroll-finger")
def try_enroll_finger(user: str = Depends(current_user), name: str = Form(...)):
    """Store a fingerprint for this person (same record as their face).
    Uses the mock sensor on the laptop and the real R307/R503 sensor on the Pi."""
    name = name.strip()
    if not name:
        return {"ok": False, "error": "enter a name first"}
    pid, _ = db.get_or_create_person(name)
    try:
        from acs.core.fingerprint import create_sensor
        sensor = create_sensor(cfg)
        slot = sensor.enroll()
        db.add_finger_template(pid, slot)
        sensor.close()
        driver = cfg.get("fingerprint.driver", "mock")
        return {"ok": True, "slot": slot, "name": name, "driver": driver}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/try/recognize")
def try_recognize(user: str = Depends(current_user), decide: int = 1):
    eng = get_engine()
    if not eng.available:
        return {"ok": False, "error": "face models unavailable"}
    frame = get_hub().frame()
    rec = eng.recognize(frame)

    # The access flow emits a ONE-SHOT event at each transition; act on it once.
    #   grant        -> registered + passed liveness    -> log GRANTED
    #   spoof        -> registered + failed liveness 10s -> log DENIED_SPOOF + capture
    #   deny_unknown -> unregistered face                -> log DENIED_UNKNOWN (no liveness)
    if decide:
        ev = rec.get("event")
        if ev:
            from acs.types import Candidate, Method
            if ev == "grant":
                cand = Candidate(rec.get("person_id"), Method.FACE, rec.get("score", 0.0),
                                 is_live=True, name=rec.get("name"), frame=frame)
            elif ev == "spoof":
                cand = Candidate(rec.get("person_id"), Method.FACE, rec.get("score", 0.0),
                                 is_live=False, name=rec.get("name"), frame=frame)
            else:  # deny_unknown
                cand = Candidate(None, Method.FACE, rec.get("score", 0.0),
                                 is_live=True, frame=frame)
            res = get_decider().handle(cand)
            rec["decision"] = res.value if res else None

    rec["recent"] = [
        {"name": r["name"], "ts": r["ts"], "method": r["method"], "result": r["result"]}
        for r in db.recent_events(6)
    ]
    return rec


@app.get("/camera/stream")
def camera_stream(user: str = Depends(current_user), overlay: str = ""):
    """MJPEG preview fed by the shared CameraHub.

    overlay=mesh draws a live FaceMesh tessellation (used on the enrollment page)."""
    try:
        import cv2
    except Exception:
        return Response("camera unavailable (opencv not installed)",
                        media_type="text/plain", status_code=503)
    import time as _t
    hub = get_hub()
    mesh = None
    monitor = None
    if overlay == "mesh":
        try:
            mesh = get_mesh_overlay()
            monitor = get_engine().monitor    # reuse the single FaceLandmarker
        except Exception:  # noqa: BLE001 - mediapipe missing -> plain stream
            mesh = None

    def gen():
        while True:
            frame = hub.frame()
            if frame is None:
                _t.sleep(0.05)
                continue
            if mesh is not None and monitor is not None:
                try:
                    pts = monitor.snapshot().get("landmarks")
                    frame = mesh.draw(frame, pts)
                except Exception:  # noqa: BLE001
                    pass
            ok, jpg = cv2.imencode(".jpg", frame)
            if ok:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
            _t.sleep(0.04)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")
