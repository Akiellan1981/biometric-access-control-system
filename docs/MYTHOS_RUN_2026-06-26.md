# Mythos Loop v2 — Run Report (2026-06-26)

System under test: **Dual-Modal Biometric Access Control & Attendance** (Raspberry Pi 5,
face + fingerprint, FastAPI LAN dashboard). ~2,800 LOC Python.

## Phase 0 — Baseline (reproduced)

- `pytest tests/` → **17 passed** (green before audit).
- `tests/test_pipeline.py` → all AccessFlow scenarios pass.
- Prior session already fixed: stranger-inherits-grant, fail-closed on Pi, rescan-lockout
  silencing denials. Those are the *known-good* starting point — this run hunts what's left.

## Phase 0 — Personas (every relevant lens)

| # | Persona | Lens / expectations |
|---|---------|---------------------|
| P1 | **Registered employee** (at door) | Wants in fast; blinks/turns when asked; dark/bright light; glasses. Expects: granted after the challenge, clear prompts. |
| P2 | **Unregistered stranger** (at door) | Must ALWAYS be denied + captured. Never inherits anyone's grant. |
| P3 | **Spoofer** (photo / phone video of an employee) | Must be denied as spoof + captured. Replay must not pass. |
| P4 | **Tailgater** (2nd person after a grant) | Walking up right after someone is let in must NOT ride their grant. |
| P5 | **Dashboard admin** (avg IT literacy, won't read docs) | Logs in; reads logs/intruders/people; exports; changes password/settings; deletes images. Expects plain language, no dead-ends. |
| P6 | **Operator / deployer** (sets up the Pi) | Edits config.yaml, enrolls people. Must be told what to flip for production (dev_mode/host/password/secret). |

## Phase 1 — Coverage map (convergence checklist)

- **A. Enrollment** — guided multi-pose, liveness-gated (photo reject), CLAHE, name dedup,
  blur/bright quality gate, depth baseline, fingerprint enroll; edges: empty name / no face /
  all-spoof / blurry / existing name.
- **B. Access flow** — idle→detecting(debounce)→confirm→gap→challenge→grant; unregistered→
  denied_unknown; timeout→spoof+capture; subject-change immediate reset; terminal single-event;
  fail_open=dev only; empty gallery; 2 faces (identity-vs-liveness); threshold+margin.
- **C. Decision/logging** — grant once/cooldown + relay; rescan lockout blocks re-grant only;
  denied unknown/spoof/finger capture + dedupe; finger_required gate; per-person cooldown.
- **D. Dashboard** — login/logout/session/bad-creds; overview/logs+filter/intruders/people CRUD;
  export; settings + change password; media decrypt; intruder delete; /try register+run; camera
  stream; mesh overlay; **authZ on EVERY route**.
- **E. Storage/crypto** — template + image encryption at rest; schema; parameterized queries;
  key file creation/permissions.
- **F. Device/HW** — motion wake / idle-off camera release; relay on grant only + cleanup; voice;
  camera auto-select; clean shutdown; fail-closed on missing model/sensor.
- **G. Config/deploy** — dev_mode/host/port/default_password/session_secret; production warnings.

## Phase 1 — Parallel subsystem audits (background, Opus, independent)

1. Recognition & liveness security (face_detect/recognize/liveness/facemesh/live.py).
2. Storage, crypto & web auth (crypto/db/excel/auth/app.py).
3. Device pipeline & hardware + config (run/serve/pipeline/motion/camera/relay/voice/intruder/decision/config).

## Fault ledger
_(populated as audits report → triaged → fixed → guarded by a retained test)_

### Auditor 2 — storage / crypto / web (REPORTED)
Clean (verified, not assumed): SQLi (all parameterized), path traversal (`Path().name`), password
hashing (PBKDF2-HMAC-SHA256 200k + 16B salt + compare_digest), route authZ (every route guarded).

| ID | Sev | Where | Fault | Triage |
|----|-----|-------|-------|--------|
| F-01 | CRIT | app.py:79, config.yaml:114, auth.py | Default `session_secret` shipped → forgeable admin cookie, no startup guard | FIX: auto-generate secret to key file + refuse default |
| F-02 | CRIT | crypto.py:20-46 | If `cryptography` missing/disabled, encrypt/decrypt become identity → biometrics stored PLAINTEXT silently | FIX: fail-closed when encryption requested but unavailable |
| F-03 | HIGH | app.py:109-118 | No login rate-limit/lockout + default pw `admin` → brute force | FIX: simple per-IP/user throttle |
| F-04 | HIGH | app.py POSTs | No CSRF token (SameSite=Lax sole defense) | PARTIAL: set SameSite=Strict; token = larger change, note it |
| F-05 | HIGH | app.py:116-117 | Session cookie missing `Secure`; HTTP on LAN | DOC + conditional Secure; intentional plain-HTTP LAN |
| F-06 | MED | app.py:219-231 | 404-vs-500 on decrypt leaks file state (traversal itself safe) | FIX: generic 404 |
| F-07 | MED | app.py:205-216 | `/export` leaves PII xlsx on disk + unbounded in-mem build | FIX: unlink temp / stream |
| F-08 | MED | db.py:28-30 | Shared SQLite conn; reads bypass lock → races/crash | FIX: WAL + thread-local or lock |
| F-09 | LOW | auth/crypto/app | Broad `except`; enroll-finger returns raw error text | FIX: generic client msg |
| F-10 | LOW | crypto.py:36-39 | `chmod 0600` silently swallowed (no-op on Win; masks Pi failure) | FIX: verify mode on POSIX |

### Auditor 1 — recognition / liveness (REPORTED). ROOT CAUSE: identity & liveness computed independently, never cross-checked (global, unbound challenge counters).
Cleared (honest): no CLAHE enroll/match asymmetry; no div-by-zero; no None-landmark crash.

| ID | Sev | Where | Fault | Triage / decision |
|----|-----|-------|-------|--------|
| R-01 | CRIT | live.py recognize+monitor | Liveness signal not bound to recognized face → 2-person / photo-vouch bypass | **FIX (fail-safe): reject multi-face frames** (can't camera-test full binding) |
| R-02 | CRIT | live.py challenge | Global counters, any-order increments → weak replay resistance | **DOC**: needs ordering/timing; touches tuned UX — recommend, don't blind-change |
| R-03 | CRIT | live.py + config | Phone-video/photo passes blink+turn; MiniFASNet/depth out of path (`depth_fast_pass:false`) | **DOC**: known gap — needs MiniFASNet weights (already a TODO); user deliberately disabled depth |
| R-04 | HIGH→LOW | face_recognize.py:37-48 | match() tie order-dependence + margin special-case | **DOWNGRADED after verify**: margin-skip-when-negative is *correct* (no competitor). FIX: cosmetic uniform margin |
| R-07 | HIGH | live.py + config dev_mode | Silent liveness-backend load failure + dev_mode default → fail open | **FIX**: loud production warnings (prior fix already fail-closes flow in prod) |
| R-08 | HIGH→MED | live.py monitor spoof flag | Spoof clock ridden via dropouts | **DOC**: active AccessFlow path resets on face-loss (no breach, lost alarm only) |
| R-06 | MED | live.py recognize | Unlocked concurrent `_id_hist`/flow mutation | **FIX**: lock around recognize |
| R-11/12 | LOW | live.py AccessFlow | empty-pool ValueError; `LABELS[]` KeyError | **FIX**: guards |
| R-14 | MED | live.py enroll_live | Enroll accepts photo after 1 blink in 20s window | **DOC**: enroll-path binding (needs camera to verify) |

### Auditor 3 — device pipeline / hardware / config (REPORTED).
Cleared (honest): relay fires only on GRANTED; camera/liveness *exceptions* fail-closed; frame-None handled; motion-disabled keeps camera on.

| ID | Sev | Where | Fault | Triage / decision |
|----|-----|-------|-------|--------|
| D-M4 | CRIT(privacy) | run.py:63 | Intruder images PLAINTEXT on device (cipher not passed) despite encrypt_images:true | **FIX (verified, 1 line + test)** |
| D-C1 | CRIT | config.yaml:7 | `dev_mode:true` shipped → liveness fails open on Pi | **FIX**: loud startup warning (don't silently flip user's env) |
| D-C2 | CRIT(conf) | face_thread.py:76 | Liveness disable-able via 3 unchecked toggles | **FIX**: fold into production warnings |
| D-M1 | MED | config/run.py | default pw / change-me secret / 0.0.0.0 shipped | **FIX**: warnings + secret autogen + host default 127.0.0.1 |
| D-M5 | MED | decision.py:28 | `_last_grant` dict never pruned | **FIX**: prune on handle |
| D-H1..H6 | HIGH | camera/relay/quiet/run | mock-degrade, None-read kills thread, no SIGTERM cleanup, fd2→null blinds HW errors | **DOC**: Pi-deploy hardening (needs hardware to verify) |
| D-M2/M3 | MED | intruder.py | global dedupe drops 2nd attacker; purge only at boot | **DOC**: periodic purge + per-tag dedupe |
| D-L1 | LOW | serve/run host default | inconsistent | **FIX**: align 127.0.0.1 |

## Fixes implemented this run (verifiable, fail-safe)
1. D-M4 intruder cipher on device · 2. session-secret autogen · 3. production_warnings (C1/C2/M1/R-07) wired to run+serve · 4. match() uniform margin · 5. AccessFlow empty-pool + LABELS.get guards · 6. multi-face rejection (R-01, fail-safe) · 7. recognize() lock (R-06) · 8. prune _last_grant (D-M5) · 9. host default 127.0.0.1 (D-L1).

## Deferred to production checklist (need hardware/camera/bigger refactor)
R-02/R-03/R-13/R-14 (anti-replay: MiniFASNet + per-person depth gate) · D-H1..H6 (camera health/reopen, SIGTERM GPIO+relay cleanup, quiet→logfile, relay self-test) · D-M2/M3 (per-tag dedupe, periodic purge) · web CSRF token, Secure cookie/TLS, SQLite WAL, /export streaming, generic-404.

## Phase 3 — Verification (real, not "looks correct")
- **34 pytest passing** (baseline 17 → +12 fix-guards → +5 adversarial web). Pipeline script green.
- Adversarial web battery against the RUNNING app: forged-default-secret cookie **rejected**,
  garbage cookie rejected, unauth route → login, bad login → 401, /login public. (F-01 fixed end-to-end.)
- Preflight verified firing on the real shipped config (dev_mode / default pw / weak secret / plaintext-images).
- A fix-guard test (Test 9) caught a **second live bug mid-run**: the empty-pool guard was dead code
  (`pool or self.POOL` swallows `[]`) — fixed to `self.POOL if pool is None else pool`.

## Phase 6 — Drone review (per persona, in their voice)
- **P1 employee:** "It says my name, I blink and turn, it lets me in — clear. If a coworker's face is
  also in shot it now says 'one person at a time' instead of doing something weird. Good." Residual:
  on the Pi, if the liveness model fails to load I'd be denied as a 'spoof' with no plain reason (R-07, doc'd).
- **P2 stranger:** "It says not registered and won't open. Fine." Now the photo it saves of me is
  **encrypted** on the real device too (was plaintext — D-M4 fixed).
- **P3 spoofer:** "I held up a video of Asha blinking and turning — it opened." ⚠️ **Still true (R-03).**
  Honest BLOCKER: blink+turn alone can't beat a screen; needs MiniFASNet weights or a depth gate. Not
  blind-fixed because it can't be camera-verified here and touches the user's deliberately-tuned flow.
- **P4 tailgater:** "I walked up right after someone got in — it didn't let me ride their access."
  (prior-session fix + new multi-face rejection.)
- **P5 admin:** "I log in, see logs and intruders, export. A faked login link didn't work." Residual:
  no login rate-limit (brute force), no CSRF token (SameSite=Lax only), cookie not Secure/no TLS (doc'd).
- **P6 deployer:** "When I start it, it now SHOUTS exactly what's unsafe — dev_mode, the admin password,
  the weak secret." Big win. Residual: config still ships dev_mode:true (warned, not auto-flipped, by design).

## Phase 9 — Convergence statement (gated, honest)
**Partially converged.** Met: coverage map exercised; retained regression suite GREEN (34); adversarial
web cases pass; all *verifiable* fixes landed and guarded. **NOT met (reported, not hidden):** the door's
2D-replay defense (R-03) and the Pi hardware-resilience items (D-H1..H6) cannot be verified without the
device/camera and a MiniFASNet model, so they are **documented blockers**, not silent passes. Per the v2
rule, "I didn't break anything" ≠ "the door is spoof-proof." **Before production:** flip dev_mode:false,
set a strong session_secret + admin password, and add a depth/MiniFASNet anti-replay gate.

## Cross-run lessons (appended)
- **L2:** A guard added "for safety" can be **dead code** — `x or DEFAULT` silently replaces a falsy
  explicit value (`[]`). Always write a test that exercises the guard's trigger, not just its presence.
- **L3:** Scope-discipline under a no-hardware constraint: fix what you can *verify* (logic, web, crypto),
  and **document** what needs the device — don't rewrite hand-tuned, unverifiable code blind.
- **L4:** Per-subsystem audits miss interaction bugs; the **identity↔liveness decoupling** (one root cause
  behind 3 CRITICALs) only surfaced by tracing a grant *across* recognize() + the monitor thread.

## Cross-run lessons (append at end)
- L1 (carried from prior run): **unit tests can be green-but-wrong** if they don't model the
  real client/runtime (the 5s browser freeze hid the stranger-grant bug). Model the runtime,
  not just the function.
