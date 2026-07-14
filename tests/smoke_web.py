"""Quick manual smoke test of the dashboard (not part of pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from acs.web.app import app

c = TestClient(app, follow_redirects=False)

r = c.get("/")
print("GET / (no auth):", r.status_code, "->", r.headers.get("location"))
assert r.status_code == 302

r = c.get("/login")
print("GET /login:", r.status_code)
assert r.status_code == 200

r = c.post("/login", data={"username": "admin", "password": "admin"})
print("POST /login good:", r.status_code, "cookie set:", "acs_session" in r.cookies)
assert r.status_code == 302

r = c.post("/login", data={"username": "admin", "password": "wrong"})
print("POST /login bad:", r.status_code)
assert r.status_code == 401

c2 = TestClient(app)  # follows redirects, keeps cookies
c2.post("/login", data={"username": "admin", "password": "admin"})
for path in ["/", "/logs", "/intruders", "/people", "/settings"]:
    r = c2.get(path)
    print(f"GET {path}:", r.status_code)
    assert r.status_code == 200

r = c2.get("/logs/table?result=granted")
print("GET /logs/table?result=granted:", r.status_code, "rows contain 'granted':", "granted" in r.text)

r = c2.get("/export")
print("GET /export:", r.status_code, r.headers.get("content-type", "")[:40])
assert r.status_code == 200

print("\nSMOKE OK")
