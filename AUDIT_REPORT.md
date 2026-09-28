# SMART QR ATTENDANCE — ARCHITECTURE BASELINE AUDIT
**Audit date:** 2026-09-28 (Asia/Kolkata)  
**Auditor:** Principal Architect + Staff Full-Stack + Security + QA (audit-first pass)  
**Mode:** READ-ONLY — no code modified, no schema migration, no feature added. Verified against **actual repository** at `mohnishshanmugavadivel1-dotcom/smart_qr_attendance@75f0b38`.

> Scope: entire Django+Channels codebase (not React/Express despite prompt template). Previous AI-generated reports were **not** trusted; every claim below was traced via `find`, `cat`, `git log`, and live `test`/`check` runs before writing.

---

## 1. CURRENT SYSTEM OVERVIEW

**One-liner (verified):** Teacher (authenticated `role=teacher`) creates a 30s `AttendanceSession` (token `secrets.token_urlsafe(32)`) for a `ClassRoom × Subject`. Many enrolled students reuse *same* QR/session, but each student gets **at most one `AttendanceRecord` per session** (`unique(session,student)`). Identity is **server-derived `request.user`**, not client `student_id`. Student must complete **Location (mandatory, ≤50 m) → QR scan (server validation, heartbeat 3 s, timeout 15 s) → 10 s verification (still `OPEN`) → `SUCCESS` → `PRESENT`**. Teacher monitors live via **WebSocket + 2 s polling fallback**, can `Manual Mark` or `Finalize → ABSENT` for remainder. History/Analytics/CSV follow.

**Stack (verified `requirements.txt`/`runtime.txt`/`config/settings.py`):**
- Python 3.13, Django 6.1.1, `daphne 4.2.1`, `channels 4.3.1` (+ `channels_redis 4.3.0` optional), SQLite dev / `dj-database-url` Postgres prod, `whitenoise` static, `qrcode[pil]`, `Pillow 11.3`, `django-channels`.
- Auth: `AbstractUser` extended `role ∈ {teacher,student}`, `roll_number`, `phone`; session cookies `HttpOnly`, `SameSite=Lax`, `pbkdf2`; `LOGIN_URL /accounts/login/`.
- QR: `qrcode` with `ERROR_CORRECT_H`, payload `f"{base}/attendance/verify/?session={token}"` (absolute URL), rendered as `data:image/png;base64` (280 px).
- PWA: `/static/manifest.json` + `/static/sw.js` (skips `/attendance` & `/ws` fetch, installable). Font Awesome CDN, Google Fonts `Plus Jakarta Sans` + `Space Grotesk`, `jsQR 1.4.0` CDN for client decode, Chart.js in analytics (verified in `templates/attendance/analytics.html`).
- Deploy: `render.yaml` (Blueprint), `build.sh` (`pip install → collectstatic → migrate → seed_demo`), `Procfile` `daphne`, `runtime.txt python-3.13.0`.

**Topology (verified):**
```
Browser (teacher phone/laptop)            Browser (many student phones)
  │ templates/attendance/teacher_*.html      │ templates/attendance/student_*.html
  │ + teacher camera (face, optional)       │ + student camera (QR only after 75f0b38)
  │ + geolocation (teacher source)          │ + geolocation (mandatory)
  └────► Django Views (attendance/views.py) ◄──────┘
              │  ORM   │ Cache (LocMem) │ Channels (+Redis optional)
              ▼        ▼                ▼
           SQLite/PG  rate-limit     WebSocket group attendance_{session.id}
```

**Honest limit (README + code):** “Authenticated account-bound attendance with active verification, not perfect physical proof.” If attacker logs in as another account, server trusts that login (like any web app). No biometric binding pre-location/face.

---

## 2. ACTUAL FILE STRUCTURE

```
smart_qr_attendance/
├── config/                  # project wiring
│   ├── settings.py          # 300+ lines: ALLOWED_HOSTS*, CSRF_TRUSTED_ORIGINS, DB url, CACHES LocMem, CHANNELS InMemory/Redis, QR timers, LOGGING, whitenoise
│   ├── urls.py              # admin, health/, /, dashboard/, accounts/, classroom/, attendance/
│   ├── asgi.py              # ProtocolTypeRouter: http → django_asgi, websocket → AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(attendance.routing)))
│   ├── wsgi.py
│   └── health.py            # GET /health/ → {status, time, db: SELECT 1}
├── accounts/                # identity
│   ├── models.py            # User(AbstractUser) role, roll_number
│   ├── views.py             # register_view, login_view (rate-limit 5/300s, 10/300s, safe-redirect url_has_allowed_host_and_scheme), logout_view GET/POST
│   ├── forms.py             # RegisterForm enforces teacher/student branch
│   ├── urls.py, admin.py, tests.py (empty placeholder)
│   └── migrations/0001_initial.py
├── classroom/               # roster
│   ├── models.py            # ClassRoom(code unique, teacher FK), Subject(code unique), Enrollment(unique student,classroom)
│   ├── views.py             # classroom_list, create_classroom/subject, manage_enrollment, enroll_self — with CODE_RE/NAME_RE regex, duplicate checks
│   └── migrations/0001_initial.py
├── attendance/              # CORE
│   ├── models.py            # Session, Attempt, Record, LocationDenial (see §9)
│   ├── views.py             # ~1050 lines: teacher_* , student_* , api_* (start/scan/heartbeat/invalidate/face/complete/location-denied, teacher-location, toggle-face, teacher-verify-face)
│   ├── urls.py              # 16 routes under /attendance/
│   ├── consumers.py         # AttendanceConsumer: AuthMiddlewareStack, _is_allowed() (teacher or enrolled), group attendance_{id}
│   ├── routing.py           # ws/attendance/<session_id>/
│   ├── utils.py             # generate_qr_base64, get_qr_payload, haversine_meters
│   ├── admin.py, apps.py, tests.py (11 real tests), management/commands/seed_demo.py
│   └── migrations/0001_initial (sessions/attempts/records) + 0002 (+location/face + LocationDenial) + 0003 (+teacher_accuracy, student_accuracy, face_verified_by_teacher)
├── templates/
│   ├── base.html            # glass navbar, a11y skip-link, focus-visible, reduced-motion, POST logout, aria-live messages, loader anti-double-submit
│   ├── 404.html, 500.html
│   ├── accounts/login.html, register.html (labels ↔ id_* , autocomplete, aria-required/invalid)
│   ├── attendance/teacher_dashboard.html, teacher_session.html (556 lines), teacher_history.html, analytics.html, student_dashboard.html, student_verify.html (now ~545 lines, post-75f0b38), student_history.html
│   └── classroom/list.html, manage.html
├── static/manifest.json, sw.js   # PWA; sw skips /attendance & /ws
├── staticfiles/ (364 post-processed, manifest)
├── requirements.txt, runtime.txt, render.yaml, build.sh, Procfile, README.md, UPGRADE_NOTES.md, DEPLOY_RENDER.md, AUDIT_REPORT.md (this)
├── db.sqlite3 (773 files total incl. .git/objects)
└── .git/ (main @75f0b38, origin mohnishshanmugavadivel1-dotcom/smart_qr_attendance)
```

**No React/Express/Socket.IO** found despite prompt template — actual realtime is **Django Channels WebSocket** (`channels.layers`, `group_send type attendance.update`), not `socket.io`. No `package.json`, `Vite`, `node_modules` observed.

---

## 3. QR FLOW — DEEP AUDIT (current, post-75f0b38)

### 3.1 Teacher trace (verified `attendance/views.py::create_session`, `teacher_dashboard.html`, `teacher_session.html`)

1. **Login** `POST /accounts/login/` → `login_view` (rate-limit 10/300s, `url_has_allowed_host_and_scheme` guard on `next`). Teacher `role=teacher` or `superuser` passes `teacher_required` guard.
2. **Select class/subject** `teacher_dashboard.html` → form `POST /attendance/session/create/` with `classroom (FK must belong to teacher)`, `subject`, `allowed_radius_meters` (10–500 clamped, default 50), `teacher_latitude/longitude` (optional from JS), `face_verification_enabled` (bool).
3. **Create session** `create_session()` → `AttendanceSession.objects.create(teacher=request.user, classroom, subject, face_enabled, radius, lat/lng, updated_at=now if lat/lng)`. Token `secrets.token_urlsafe(32)` max 64, `expires_at = now+QR_EXPIRY_SECONDS (30 env)`. Saves synchronously. Returns `JsonResponse` for XHR or `redirect teacher_session`.
4. **Generate QR** `get_qr_payload(request, token)` → `f"{scheme}://{host}/attendance/verify/?session={token}"`; `generate_qr_base64(payload)` → `data:image/png;base64,……`. `teacher_session.html` shows `qr_b64` 280 px, `payloadBox`, `countdown` countdown JS (`expiresAt = session.expires_at|date:'c'`) polling `progressBar` width.
5. **Display QR** `teacher_session_view(request, session_id)` (must own session: `get_object_or_404(... teacher=request.user)`). Builds `students_data` bulk (records dict, denials_map single query, latest_attempts single ordered sweep — N+1 fixed). Renders live controls: face toggle, teacher camera, teacher location `Capture`, denials red card, face queue, attendance table, finalize.
6. **Session expiry** `is_expired() = now >= expires_at OR status==EXPIRED`; `expire_if_needed()` flips `OPEN→EXPIRED` on read. `is_active() = OPEN && now<expires_at`. Frontend countdown turns `EXPIRED` at 0, but **valid scan at 29.9s proceeds to 10s verification** (see student). `finalize` allows `EXPIRED` → `CLOSED` after explicit confirm not needed (hardblock only for manual before expiry). QR reuse after expiry → `400 error QR expired` on `api_scan`.

*Recent delta:* now includes teacher `accuracy` (`teacher_location_accuracy`) from JS best-single 7s attempt, `allowed_radius`, `face_verification_enabled` badge; teacher camera previously used for own liveness, now **teacher-side student face capture** (new `teacher-verify-face/` endpoint).

### 3.2 Student trace (verified `verify_page`, `student_verify.html` JS, `api_start_attempt`, `api_scan`, `api_verify_complete`, `LocationDenial`)

1. **Login** same `login_view`; pending `?session=TOKEN` preserved across login → redirects to `/attendance/verify/?session=TOKEN`.
2. **Student dashboard** `student_dashboard` (blocked for teachers) lists `enrollments → classroom_ids → ACTIVE Sessions is_active()` + `AttendanceRecord` history + `AttendanceAttempt OPEN`.
3. **QR entry/scanner** Two paths:
   - External QR decode outside app → `GET /attendance/scan/?session=TOKEN` → `scan_redirect` → `login ?session=...&next=…` or `→ verify/?session=TOKEN`.
   - In-app `Verify` page: JS uses `jsQR` on `getUserMedia(facingMode:environment)` canvas loop; manual token input fallback `?session=`.
4. **Session detection** `verify_page(request): token = GET session||token`; `AttendanceSession.get(token)` + `expire_if_needed()`; fallback: if no token but student has enrolled class with an `OPEN` active session, pick first `OPEN` as fallback. Sets `already_present` (`AttendanceRecord PRESENT` exists), `not_enrolled` (no Enrollment), `open_attempt` (latest `OPEN`, staling `INVALID` if `is_stale()` >15s), `location_denied` (`LocationDenial` exists), `is_active/is_expired` flags.
5. **Attempt creation** User clicks `#startBtn` → JS `captureLocation()` (**single high-accuracy 7s cap**, new fast path; previously attempted best-of-3 3×12s which caused >30s blocking). On success gets `studentLat/lng/acc`, updates `sLat/sLng ±acc`, computes `distanceM = haversine(student, teacher)`. Calls `POST /api/attempt/start/` JSON `{token, latitude, longitude, accuracy}`.
   - `api_start_attempt` rate-limit 20/60, token len <200, enroll check 403, `PRESENT` already 409, **location required else 400 `location_required` → frozen overlay**, `teacher_location_missing` 400, distance computed `haversine_meters`, early out if `>radius` allowed but flagged `location_verified=False` (final check still enforces). Sweep stale `OPEN` → `INVALID`. If existing `OPEN`, returns `409 already_open` (resume). Else `create AttendanceAttempt(attempt_number=last+1, student_lat/lng/acc, distance, location_verified, last_heartbeat=now)` (accuracy stored, fallback if migration missing). Deletes prior `LocationDenial` for this student/session on success.
6. **Preparation** **REMOVED** in `75f0b38`: previously `prepState` 10s (`prepLeft 10 → 0, heartbeat 3s, visibilitychange INVALID`). Current: **no prep gap**; `startAttempt` success → `showState('scan'); startCamera(); setStep('scan')` immediately. Saves 10s.
7. **QR decoding** Already captured via JS `jsQR` loop or manual input. User taps `Verify Scan`.
8. **Server validation** `POST /api/attempt/<id>/scan/` (rate-limit 30/60) with `{token, latitude?, longitude?, accuracy?}`.
   - `attempt.status != OPEN` → 400.
   - Extract token: supports full URL `?session=` parsing.
   - Token must match `session.token` else `400 Invalid QR token`.
   - `session.is_expired()` at scan time → `400 QR has expired` (prevents replay after expiry).
   - Enrollment + already `PRESENT` → `INVALID` 409.
   - Optionally updates `student_lat/lng/distance/location_verified` if fresh coords supplied (now includes `accuracy`).
   - Sets `scan_verified_at=now`, `last_heartbeat=now` → `200 success`.
9. **Verification** JS `startVerify()` → `showState('verify')` 10s countdown (`verifyLeft 10 → 0, progress`).
   - `checkFaceToggle()` polling informs `teacher_side` but **no student camera** anymore. Message: `Teacher will verify your face in person` if `face_enabled`.
   - At `verifyLeft==0`: `POST /api/attempt/<id>/complete/` (rate-limit 10/60).
   - `api_verify_complete` checks: `OPEN` else 400, `scan_verified_at` must exist else 400, `CLOSED` → `INVALID`, duplicate `PRESENT` → `INVALID` 409, **location null → 400 `location_required`**, recomputes `dist = haversine(student, teacher_latest)`, updates `distance/location_verified`, if `not location_verified` → `400 out_of_range: You are Xm away. Must be within Ym` (keeps `OPEN` for retry), **face check** if `face_verification_enabled && !face_verified` → `400 face_required teacher_side: Ask teacher to capture your face via TEACHER camera`** (previously student had to upload via `/face/`; now student never sets it, teacher must via `/teacher-verify-face/`).
   - On pass: `transaction.atomic get_or_create AttendanceRecord(session,student) → PRESENT QR` with `student_lat/lng/distance/face_verified`; sets `attempt.status=SUCCESS`; deletes `LocationDenial`; `group_send attendance_{session.id} type attendance.update` with `{present_count, student, roll, method, distance, face, time}`.
10. **PRESENT** `showSuccess(distance)` renders confetti, `PRESENT` badge, distance & accuracy.

*Heartbeat/invalidation interleaved:* While `OPEN` (scan or verify), `startHeartbeat` POST every 3s to `/heartbeat/` updating `last_heartbeat`; server `is_stale() = now-last_heartbeat >15s` sweeps `INVALID` (in `session_status_api` and `verify_page`). `visibilitychange hidden + 1s → POST invalidate` plus `pagehide sendBeacon`. Short blips tolerated.

*Failure modes:* `frozenOverlay` on `location_required/denied` → `POST /api/location-denied/ token reason` creates `LocationDenial(unique session,student)` → teacher denials card updates via WS/polling. Student frozen until `retryLocation()` grants permission.

### 3.3 What changed in recent QR modifications (git log)

- `8a9bba2 final: hardened SmartQR` (large): added location (50m geofence mandatory, frozen overlay, teacher location source, denials) + face toggle + 10s prep/verify/heartbeat/visibilitychange + atomic `unique` + WS authz + rate-limits + a11y/pagination hardening.
- `345c7ff fix: move face scan to teacher portal only, remove 10s prep gap, fix location accuracy best-of-3` : **Moved face camera from student to teacher** (new `teacher-verify-face/` endpoint, `face_verified_by_teacher`, `student_location_accuracy`, `teacher_location_accuracy`; student no longer shows `faceVideo`/`FaceDetector`); **removed 10s prep** (idle→scan directly); changed student steps to `Location/Scan/Verify/Present`; introduced `best-of-3` 3×12s accuracy (intended fix for 21m offset, but caused 30s+ block).
- `75f0b38 fix: real-world 5-7s fast path` : **Reverted best-of-3 to single 7s cap** (`getBestPosition(7000)` single promise with 7.5s hard timeout), reuse cached loc (no double 7s), `triggerScan` no longer re-captures, `startAttempt` reuses if already have coords, teacher `getBestPosTeacher` also single 7s. Fixes QR expiry race; keeps `±Xm` display.

*Impact:* Student JS now ~545 lines (was 649), teacher JS +126 lines for teacher face capture; both now pass `accuracy` to server; migration 0003 added 3 fields.

### 3.4 Accidentally affected?
- `best-of-3` accidentally made location >30s → QR expired → **regression** (P0) fixed in `75f0b38`.
- Face move changes verified via `api_verify_complete` message dependency: clients expecting `face_required` from student upload now get teacher-side message — old automated tests that upload `face_image` still pass because `face_verified=True` still satisfies check, but **new flow has no automated coverage for teacher capture** (gap).
- Location accuracy fields added nullable with fallback `try/except` → safe for old DB; no schema break.

---

## 4. STATE MACHINE

### 4.1 Backend `AttendanceSession` (`models.AttendanceSession.status`)
```
          create(token, expires=now+30s)
OPEN ─────────────────────────────────────► EXPIRED (expire_if_needed, time >= expires_at)
 │  │                                         │ (can still verify if scan already done)
 │  └────────► CLOSED (finalize_session, atomic select_for_update) → finalize creates ABSENT for remaining
 │              │
 └─────────────┘
```
- `is_active() = OPEN && now<expires_at`
- Legal: `OPEN→EXPIRED` (time), `OPEN→CLOSED`, `EXPIRED→CLOSED`.
- Illegal: `CLOSED→*`, `EXPIRED→OPEN`.

### 4.2 Backend `AttendanceAttempt` (`models.AttendanceAttempt.status`)
```
               create (OPEN, attempt_number = last+1)
OPEN ──┬──► SUCCESS (api_verify_complete → get_or_create Record PRESENT)
       ├──► INVALID (is_stale>15s sweep, visibilitychange/pagehide, heartbeat miss, duplicate PRESENT, manual invalidate, not enrolled, token mismatch, session CLOSED)
       └── stays OPEN during prep/scan/verify (heartbeat every 3s, last_heartbeat updated)
```
- Sweep: `session_status_api` iterates `OPEN` attempts and marks stale `INVALID`.
- `unique_together (student, session, attempt_number)` → many INVALID→new OPEN per student/session, but only latest `OPEN` kept.

### 4.3 Backend `AttendanceRecord` (`unique(session,student)`)
```
PRESENT (QR)  ← api_verify_complete SUCCESS path (atomic get_or_create, status PRESENT method QR + snapshot lat/lng/dist/face)
PRESENT (MANUAL) ← manual_mark (teacher, confirm if EXPIRED)
ABSENT ← finalize_session creates for every enrolled without PRESENT (never downgrades PRESENT)
```

### 4.4 Frontend `student_verify.html` state (`state` var)
```
idle (Location card, Start button)
  │ location OK + POST start OK (heartbeat 3s)
  ▼
scan (jsQR camera, token input) — OFF prep gap since 75f0b38
  │ scan_verified_at set (POST scan OK)
  ▼
verify (10s countdown) — may receive teacher face_required → stays verify but error at complete
  │ complete POST OK
  ▼
success (PRESENT, confetti, heartbeat stopped)
 
INVALID branch reachable from idle/scan/verify via: stale, visibility hidden 1s, heartbeat 400, out_of_range, teacher_location_missing, location_required, face_required, network, expired QR, already present

Frozen overlay orthogonal: shown on location_required/denied, blocks idle→scan until retryLocation success (deletes LocationDenial on next start success).
```
- Old states `prep (10s)` and `face (student camera)` **removed** (still listed in §4 prompt template but not in current code after 345c7ff).
- Legal transitions enforced by `attempt.status==OPEN` guard on every `api_scan/heartbeat/complete/face`; illegal if `SUCCESS/INVALID`.

### 4.5 Frontend `teacher_session.html`
```
OPEN (countdown 30s, progress) → EXPIRED (badge, notice) → CLOSED (finalize button → Closed)
Polling 2s + WS attendance_{id} updates: present_count, denials, face_enabled, teacher_location, present_list
Face queue: OPEN attempts with non-empty face_image (now teacher-captured)
```

---

## 5. IDENTITY MODEL

- **Teacher identity:** `request.user` (`AbstractUser`, `role=teacher` or `superuser`). Guards: `@login_required` + `@teacher_required` wrapper checks `is_teacher() || is_superuser || HttpResponseForbidden`. Classroom ownership: `get_object_or_404(ClassRoom, id=classroom_id, teacher=request.user)` — cannot create session for another teacher's class. Session ownership: `get_object_or_404(AttendanceSession, id=session_id, teacher=request.user)` for `teacher_session_view`, `manual_mark`, `finalize`, `teacher-location`, `toggle-face`, `teacher-verify-face` — IDOR blocked → 404 if other teacher. WS `_is_allowed`: `user==session.teacher OR is_superuser OR Enrollment exists`.

- **Student identity:** `request.user` (`role=student`, optional `roll_number`). **Never trusts** `student_id` from client for final write: `api_start_attempt`, `api_scan`, `api_heartbeat`, `api_invalidate`, `api_face_verify`, `api_verify_complete` all do `get_object_or_404(AttendanceAttempt, id=attempt_id, student=request.user)`. `AttendanceRecord` creation uses `student=request.user`. Enrollment checked via `Enrollment.objects.filter(student=request.user, classroom=session.classroom).exists()` → 403 if outsider.

- **Enrollment:** `Enrollment(student, classroom)` `unique_together`. Server derives set for session; no client list trusted. `student_dashboard` and `verify_page` fallback use same enrollment query.

- **Session ownership:** token is **random** `token_urlsafe(32)` (192 bits), `unique`, `db_index`, max 64. Queried by `token` on start/scan/complete/denied; not guessable. Payload includes full URL but token is the secret. QR payload `base/attendance/verify/?session=TOKEN` — open to anyone with link, but final write requires enrolled authenticated user.

- **Attempt ownership:** `attempt.student FK` + `student=request.user` filter. `LocationDenial(session, student)` unique prevents spam.

- **Client-supplied identity values trusted?** Audited: **No** `request.POST['student_id']` trusted for PRESENT except `manual_mark` and `teacher-verify-face` where value is **student to mark, not actor**: actor still `request.user` (teacher) and teacher must own session/class; target existence checked `User(role=student)` + enrollment. Not spoofable to impersonate actor. No `roll_number` trusted for write.

**Gap:** `manual_mark` does `request.POST.get('student_id')` without additional `limit_choices_to` but checks enrollment; `teacher-verify-face` similarly. Rate-limits via cache `rl:att:*:{ip}:{uid}` but not cryptographically tied. No JWT; session cookie only.

---

## 6. ATTENDANCE INVARIANTS

**Primary invariant (verified in `models.AttendanceRecord.Meta.unique_together = ('session','student')`):**
> **For any (session, student), at most one `AttendanceRecord` row exists.** Enforced at **DB constraint** + **atomic `get_or_create` inside `transaction.atomic`** in both `api_verify_complete` and `manual_mark`. `IntegrityError` caught → `409 Already marked`. `finalize_session` uses `select_for_update` on session + loops enrollments, checking `present_ids` set, `create` ABSENT per missing student with `IntegrityError` tolerance (race where student becomes PRESENT concurrently).

**Many-to-one session:** Many students may use one `AttendanceSession` (token shared). Verified: `create_session` creates single session per classroom/subject; no per-student session.

**Final-record vs attempt cardinality:**
- `AttendanceAttempt.unique = (student, session, attempt_number)` → **many attempts per student/session** (retries after `INVALID`).
- Only `SUCCESS` → `PRESENT` Record. `INVALID` attempts do not create records.
- `verify_page` guards `already_present = AttendanceRecord PRESENT exists → show "already PRESENT", block start`.

**Geofence invariant:** `api_start_attempt` recomputes `dist = haversine(student, teacher)` and stores `location_verified = dist <= radius` (radius `allowed_radius_meters` per session, 10–500). `api_verify_complete` recomputes with latest teacher location and **rejects if `not location_verified`** → `400 out_of_range` (keeps `OPEN` for retry nearer). No bypass: client distance ignored, server recomputes.

**Face invariant:** If `face_verification_enabled=True`, `api_verify_complete` now requires `attempt.face_verified=True` (set via either student `api_face_verify` legacy or teacher `api_teacher_verify_face`). After move to teacher-only, student path leaves `face_verified=False` → `400 face_required teacher_side` until teacher captures. `finalize` still creates `ABSENT` irrespective of face.

**Closed invariant:** `CLOSED` blocks `manual_mark`, `finalize` re-entrance, `api_start_attempt`, `api_scan`, `api_update_teacher_location`, `api_toggle_face`, `api_teacher_verify_face` → 400.

**Tested (allowed vs illegal):**
- Legal: `OPEN→scan→verify 10s→SUCCESS→PRESENT`, `OPEN→INVALID→new OPEN`, `EXPIRED scan at 29.9s → verify finish after expiry → SUCCESS` (verifies `scan_verified_at` exists, not QR alive).
- Illegal (blocked 400/409): `scan with wrong token`, `scan expired QR`, `complete without scan_verified_at`, `complete outside 50m`, `complete without face when required`, `duplicate PRESENT`.

---

## 7. SECURITY AUDIT

*Tested only this app, no external exploitation.*

| Category | Finding | Evidence / Endpoint | Severity |
|---|---|---|---|
| **AuthN bypass** | `login_view` rate-limit 10/300s via LocMemCache per IP, but cache per-process (`InMemory` without Redis) → bypass across workers. No lockout. | `accounts/views.py:_rate_limit` + `settings.CACHES LocMem` | **P1** |
| **Open redirect** | Fixed but needs regression: `_is_safe_url` uses `request.get_host()` now (previously arbitrary). `next=/dashboard/` validated, `session` param appended only if safe. | `accounts/views.py:_is_safe_url`, test `test_open_redirect_protection` | **P1** (now GREEN) |
| **Logout CSRF** | `logout_view` allows `GET` (comment says UX) → `<img src="/accounts/logout/">` logs victim out. Not data theft but `P1`. Should be POST-only. | `accounts/views.py:logout_view @require_http_methods(["GET","POST"])` | **P1** |
| **AuthZ bypass teacher** | Fixed to 404 if `teacher != session.teacher` on `teacher_session_view`, but `session_status_api` allows enrolled student to see `present_list` (intentional). IDOR on teacher analytics/history is correctly `filter(teacher=request.user)`. | `views.session_status_api` check `request.user != session.teacher` then enrollment | **P1** (now RED-safe) |
| **IDOR attempt spoof** | Blocked: `get_object_or_404(AttendanceAttempt, id=..., student=request.user)` — cannot act on another student's attempt. Verified. | `api_scan/heartbeat/face/complete/invalidate` | **P0** (correct) |
| **Enrollment bypass** | Blocked: every `api_start/scan` checks `Enrollment exists` → 403. Tested `test_student_must_be_enrolled`. | `attendance/views.py` ~10 sites | **P0** |
| **Direct PRESENT creation** | No endpoint allows `POST /records` with arbitrary student. Both `api_verify_complete` and `manual_mark` derive student from `request.user` or teacher-checked target; `manual_mark` requires teacher owner. | `attendance/views.py` | **P0** |
| **Duplicate PRESENT** | DB unique + atomic `get_or_create` + 409; race yields `IntegrityError`. Verified `test_duplicate_prevention`. | `models.AttendanceRecord` | **P0** |
| **QR replay / expiry bypass** | Server time `is_expired()` checked on `api_scan` (and `api_start`); token length capped 200 to prevent DoS; payload URL parsing extracts `session` param robustly. Replay of stolen token before expiry from another enrolled student **is not blocked** except enrollment — token is shared by design; threat is enrollment gate, not token secrecy. Post-expiry replay blocked. | `utils.get_qr_payload`, `views.api_scan` | **P1** (design: token is bearer for class, not per-student secret) |
| **Timestamp manipulation** | Client time ignored; heartbeat `last_heartbeat = timezone.now()` server time; expiry uses server `now`. | `views.api_heartbeat`, `models.is_stale` 15s | **P1** (now safe) |
| **Heartbeat manipulation** | Rate-limit 60/60 per user via cache; throttled → 429, not overwrite. `is_stale` 15s sweep marks INVALID, tolerates blip. | `_rate_limit heartbeat` | **P2** |
| **Socket.IO / WS room abuse** | Fixed: `AttendanceConsumer._is_allowed` checks `user==teacher OR enrolled` before `group_add`; otherwise 4403. InMemory without Redis still isolated per process. | `attendance/consumers.py` | **P1** (now GREEN, was P0 open to any authed user pre-8a9bba2) |
| **Sensitive data exposure** | `AttendanceAttempt.face_image` (base64) stored `TextField`, returned in `teacher_session.html` face queue `<img src="{{a.face_image}}">` — accessible to any authenticated teacher of session (ok) but no expiry/retention policy; PWA cache skips `/attendance` & `/ws` (correct). CSV export leaks `distance, face` but only to teacher. | `templates/attendance/teacher_session.html` | **P1** (privacy retention) |
| **Face image DoS** | `DATA_UPLOAD_MAX_MEMORY_SIZE 2 MB`, `validate` JPEG/PNG prefix, contains `;base64,`, length 300k cap, truncate 200k server-side. | `views.api_face_verify`, `api_teacher_verify_face`, `settings` | **P2** |
| **Rate-limit fragility** | `LocMemCache` per-process key `rl:att:{key}:{ip}:{uid}` — IP spoof via `X-Forwarded-For` first value taken, not validated against `Proxy` list; could be bypassed with fake header until Redis. | `_rate_limit` | **P1** |
| **XSS** | Base template escapes `{{ payload }}` via auto-escape; `present_list` JSON not `safe`. Font Awesome CDN `crossorigin/referrerpolicy` present. `SECURE_CONTENT_TYPE_NOSNIFF` ON. No `|safe` over user input found. | `config/settings.py` | **P2** |
| **CSRF** | `CsrfViewMiddleware` on, `X-CSRFToken` on every `fetch`; `ALLOWED_HOSTS *` when DEBUG True opens DNS-rebind (dev only). Prod `DEBUG False` locks `RENDER_EXTERNAL_HOSTNAME`. | `settings` | **P1** |

No P0 open bypass found **as of 75f0b38** after hardening; most P0 are now mitigated (unique + authz). Remaining P1 are operational/privacy.

---

## 8. RECENT QR CHANGES — HIGH PRIORITY DEEP DIVE

### WHAT CHANGED (from git log + diff stat)
- **8a9bba2** (baseline hardening): Added **location mandatory** (geofence 50 m, `has_teacher_location`, `LocationDenial`, frozen overlay), **face toggle** (student camera `FaceDetector`, `/api/attempt/<id>/face/`), **heartbeat/verification** (3s, 15s timeout, `visibilitychange/pagehide` → INVALID), **atomic `finalize`**, **rate-limit**, **WS authz**, **a11y**, **pagination**, **health**.
- **345c7ff**: **Moved face to teacher** (new `teacher-verify-face/`, `face_verified_by_teacher`, `student_location_accuracy`, `teacher_location_accuracy`; student `student_verify.html` stripped face camera, added `faceStudentSelect` teacher UI), **removed 10s prep** (student steps 4→3, `startPrep` deleted), **introduced best-of-3** 3×12s for accuracy (added `accuracy` param to `api_update_teacher_location`, `api_start_attempt`, `api_scan`).
- **75f0b38**: **Fixed real-world 5-7s** (reverted best-of-3 to single 7s promise with hard cap, reuse cached coords, `triggerScan` no longer re-captures, teacher+student both fast path).

### WHY
- Face: product requirement “teacher-only, manually on/off via teacher camera” — prior placed `faceVideo` in **student portal** violating spec; `21m` offset complaint revealed accuracy issue (laptop GPS `±20m`).
- Prep gap: UX complaint 10s wait before scan wasted QR 30s window.
- Location: 21m sitting offset (root cause: `±20m` WiFi geolocation, not Haversine bug).

### WHAT DEPENDS ON IT
- `TeacherDashboard → create_session(allowed_radius, face_enabled, lat/lng)` → `AttendanceSession`
- `TeacherSession` (switch, camera, location capture, denials, face queue, live table) → `api_toggle_face`, `api_teacher_verify_face`, `api_update_teacher_location`, `session_status_api`, `consumers` group `attendance_{id}` + `attendance.views.teacher_session_view` bulk queries.
- `StudentDashboard → verify_page → student_verify.html` JS: `captureLocation`/`getBestPosition`, `startAttempt`/`triggerScan`/`startVerify` → `api_start_attempt`/`api_scan`/`api_verify_complete`/`api_location_denied`/`api_heartbeat` + `LocationDenial`.
- `Analytics/History/CSV` depends on `face_verified` + `distance_meters` snapshots.

### WHAT COULD BREAK BECAUSE OF IT
- **QR expiry race** — best-of-3 broke it (P0 regression, fixed). Any future location retry loop risks same.
- **Face dependency inversion** — student `api_face_verify` still works but no UI calls it; `api_verify_complete` now returns `teacher_side face_required` message that old clients don't expect to parse (string changes).
- **`accuracy` nullable fields** require `try/except` save fallback for old DB (implemented).
- **Teacher camera constraint** — `facingMode:user` on laptop without front cam → `getUserMedia` fails → need fallback error toast (present).

### WHAT TESTS COVER IT
- 11 tests cover `create_session`, `enrollment gate (403)`, `location_required 400`, `teacher_location_missing 400`, `geofence out_of_range 400`, `face toggle (student upload → complete → toggle OFF)`, `duplicate 409`, `denial reporting`, `finalize ABSENT`, `open redirect`, `IDOR`. **Passing as of last run** (`OK` 11 in ~12s).

### WHAT IS NOT COVERED
- No test for **teacher-verify-face** (new 345c7ff endpoint) — no coverage for `teacher captures → face_verified_by_teacher → student complete` path (high risk YELLOW→RED).
- No test for **fast-path location reuse** (75f0b38) — no browser integration, no timing assertion `QR not expired before scan`.
- No concurrency test for two students completing same session simultaneously (atomic covered but not load-tested).
- No WS authz test (consumer `_is_allowed`); no PWA SW test; no heartbeat `visibilitychange` test; no pagination test for history 50 per page beyond model.

---

## 9. LOCATION FEATURE — ARCHITECTURAL ANALYSIS ONLY (no implementation recommendation beyond what’s already shipped; analysis of *future* hardening)

**Conceptual model (as shipped):** `attendance claim + current location (+ optional geofence verification)` with **teacher location as anchor** (source of truth), student location **single-shot at start/scan** (not continuous tracking). Data: `teacher_lat/lng/accuracy/timestamp`, `student_lat/lng/accuracy/distance/location_verified` per attempt + snapshot to `AttendanceRecord`. No background watch.

**Required data:** `latitude ∈ [-90,90]`, `longitude ∈ [-180,180]`, `accuracy (meters)` float; `allowed_radius_meters` per session (10–500). Server recomputes `haversine_meters` (6371000 R) — verified correct formula in `utils.py`.

**Privacy implications (P1):** Geolocation is **PII**; requires browser permission prompt. Current: stored indefinitely in `AttendanceAttempt`/`Record` + `LocationDenial` (no retention/TTL, no anonymization). EU GDPR/Indian DPDP: need explicit consent text, purpose limitation (only for attendance window), retention policy (e.g., auto-delete raw lat/lng after finalize → keep `distance` only), avoid central continuous tracking. Prompt should say “Used only to verify ≤50 m at scan time, not tracked after”.

**Server vs client responsibilities (as built):** Client captures via `navigator.geolocation.getCurrentPosition(enableHighAccuracy:true)`, displays `±Xm` and `distance`; server **recomputes** distance with latest teacher anchor and **authoritatively** rejects `out_of_range` or `location_required` (no trust). Good separation.

**Failure modes:**
- `Permission denied` → `LocationDenial(denied)` + frozen overlay till `retryLocation` → teacher notified. Good.
- `Unavailable`/`Timeout` → same denial card. Current: shows `Timeout — try near window` after 7.5s; should fallback to cached `maximumAge` reading (now 5000) but not yet.
- `Teacher anchor missing` → 400 `teacher_location_missing` blocks all students (correct).
- `Low accuracy >30m` → distance error ≈ accuracy; current: badge `±Xm` orange, no auto-compensation. Risk: sitting 0m shows 21m → still within 50m, so success, but UX confusion.
- `Teacher moves mid-session` → distance recomputed at `complete` using latest teacher anchor; student may go out_of_range after start.

**Fallback behavior (as shipped):** If student denies → frozen, cannot be PRESENT, appears in teacher `Location Denied` card; teacher may still `Manual Mark` PRESENT as override (intentional admin escape). If GPS fails → retry button, not auto-present.

**Database impact:** `AttendanceSession teacher_location_accuracy`, `AttendanceAttempt student_location_accuracy + face_verified_by_teacher` nullable → backward compatible via `migrations/0003` with `try/except` saves.

**API impact:** `api_update_teacher_location` now accepts `accuracy`; `api_start_attempt`/`api_scan`/`api_verify_complete` propagate `accuracy`; `session_status_api` returns `teacher_lat/lng` but not accuracy to student (teacher badge shows). Needs versioning if clients cache.

**Test requirements (missing):** Need browser-level geolocation mock tests (Playwright `grantPermissions(['geolocation'])` + `page.setGeolocation({lat,lng})`), accuracy edge tests (`±5m` indoors vs `±100m` cell), out_of_range loop, denial→grant transition, teacher move mid-session.

**Recommendation for next hardening (analysis only, not code):** Keep single-shot, 7s cap, reuse cache (as in 75f0b38) — do **not** add `watchPosition` continuous tracking (privacy/battery). Add retry UI with `maximumAge:30000` fallback if high-accuracy times out, and clear accuracy threshold communication (`±>30m → warning, not block`).

---

## 10. FACE FEATURE — ARCHITECTURAL ANALYSIS ONLY (teacher-only, optional)

**Purpose (as spec):** Teacher classroom presence verification / roster inspection, **not** automatic attendance overwrite. Must be `teacher-only, optional, explicitly enabled/disabled` via switch `POST toggle-face`.

**Current implementation (post-345c7ff):** Teacher camera (`getUserMedia facingMode:user` + optional `FaceDetector` fastMode) captures `data:image/jpeg;base64` (max 300 KB, truncated 200 KB) → `POST teacher-verify-face/ student_id, face_image` → creates/updates `AttendanceAttempt.face_verified=True, face_verified_by_teacher=True` + stores `face_image` TextField; `AttendanceRecord.face_verified` synced if later. Student never captures; `api_face_verify` remains for legacy but UI no longer calls it. `face_queue` in teacher session shows 10 latest `OPEN` with non-empty image.

**Camera flow issues:**
- Laptop without front cam or denied permission → `getUserMedia` rejects → alert (need more graceful fallback, e.g., file upload).
- `FaceDetector` is **browser-native, not ML recognition** — only detects bounding boxes, not identity; no embedding, no matching. True “face recognition” (compare against enrollment DB) not implemented.
- Lighting/pose false negatives: detector may miss in low light; single capture without liveness (blink) spoofable with photo.

**Needed for real recognition (analysis):**
- Enrollment: store teacher-approved reference images/embeddings per student (need `StudentFaceTemplate(student, embedding, image, enrolled_at, consent)` with consent & retention).
- Inference location: browser (TensorFlow.js face-api) vs server (Python `face_recognition`/`InsightFace`). Browser keeps privacy but model size ~5 MB; server centralizes but needs GPU.
- Confidence threshold: e.g., cosine distance <0.4 → match; need ROC tuning; false positives (stranger passes) worse than false negatives (legit fails). No threshold implemented now.
- Template storage: raw `data:image` is large, not searchable; should store embedding vector (128-d), encrypt at rest, auto-expire.
- Access control: only owning teacher + student self can view; no cross-class leakage (currently session-scoped `OPEN` queue, ok).
- Audit logging: who verified, when, confidence, image hash (not yet).
- Failure handling: if face required but capture fails → `400 face_required teacher_side` — student blocked until teacher captures; needs timeout/escalation to manual.

**Privacy (P0):** Biometric is **sensitive personal data** under GDPR Art.9 / India DPDP. Needs explicit opt-in, purpose limitation, retention (e.g., delete `face_image` after `CLOSED` + 7 days, keep boolean `face_verified` only), no cross-session reuse without consent. Current: `face_image` persisted indefinitely in DB + shown to teacher, no delete.

**Retention/access:** No TTL, no access log, no student right to delete. Should add `face_image` purge on `finalize`.

**Do not claim:** Face detection ≠ face recognition ≠ physical identity proof (photo of photo attack possible). Current system only records that teacher **captured something**, not that it matched student.

---

## 11. RESEARCH PAPER POTENTIAL

**Genuine research gap exists:** Web-based “QR + active verification” vs “QR + geofence + teacher-camera” attendance.

- **Research problem:** Can low-cost, browser-only, teacher-anchored geofence + optional teacher-camera capture reduce proxy attendance and location spoofing without continuous tracking or dedicated hardware (vs BLE beacons / RFID / fingerprint)?
- **Hypotheses:**
  1. `H1`: Geofence ≤50 m with single-shot 7s high-accuracy + teacher anchor reduces out-of-room `PRESENT` rate vs QR-only baseline (effect size).
  2. `H2`: Teacher-camera face capture (detection-only) increases perceived accountability but not true biometric accuracy vs manual roster check.
  3. `H3`: Removing 10s prep gap improves completion rate (QR expiry success) without increasing fraud.
- **Baseline system:** QR-only (`is_expired` + enrollment check) — prior `0001_initial` + heartbeat without location.
- **Experimental system:** QR + geofence (current `0002/0003` with accuracy + teacher anchor) and QR + geofence + teacher-face (345c7ff+).
- **Independent variables:** `geofence radius (50/75/100)`, `accuracy cap (7s)`, `face toggle ON/OFF`, `prep gap (0 vs 10s)`.
- **Dependent variables:** `out_of_range rejection rate`, `completion latency (start→SUCCESS)`, `QR expiry failure rate`, `false PRESENT (proxy)`, `teacher manual override rate`, `COMBINED accuracy distribution`.
- **Metrics:** `distance histogram`, `accuracy CDF`, `present_count delta`, `heartbeat dropout`, `WS live latency`, `duplicate attempt rate`.
- **Datasets/participants:** 2–3 real classes × ~40 students × 10 sessions (≥800 attendance events) with ground-truth physical headcount (research assistant manual). Include denied-location cases.
- **Methodology:** Within-subjects crossover: same class sessions alternate baseline/experimental; counterbalance order; control for device type (Android vs iOS accuracy).
- **Statistical comparisons:** McNemar for proxy rate, paired t for distance/latency, χ² for completion, ROC if face embeddings added.
- **Threats to validity:** `GPS accuracy` varied by building, weather, device; `±20m` indoors conflates true distance; `face detection` not recognition → not measuring identity; Hawthorne effect (students behave when aware); `LocMem` vs Redis channel affects WS.
- **Privacy/ethics:** IRB, informed consent for location + face image storage, data minimization (no continuous tracking, purge raw lat/lng & face_image after study), de-identified CSV, no grade penalty for opt-out.

**Verdict:** Publishable as **systems + evaluation** paper (e.g., SIGCSE, CHI Late-Breaking, IEEE TALE) if evaluation is honest about accuracy limits; not as face-recognition novelty (would need embedding + threshold study).

---

## 12. MONETIZATION POTENTIAL

**Prototype vs product gap is large — do not monetize without closing P1 security/privacy.**

- **Target customer (realistic):** Private K-12 schools, coaching institutes, skill bootcamps, SME training centers (30–500 students/class), where roster is simple and admin is single teacher. Not large universities (needs LDAP/SIS integration).
- **Value proposition:** “No hardware: teacher phone creates 30s QR, students verify with location, teacher sees live denial/face queue — replaces roll call, works on any browser, PWA installable.”
- **Deployment model:** SaaS multi-tenant (add `Tenant` / `School` FK to `ClassRoom/Session`), or self-host on Render/VPS per school. Current is single-tenant SQLite/InMemory — not SaaS-ready.
- **Pricing dimensions:** Per active student/month, per session, per teacher, storage for face images. Market in India: ₹15–30/student/month competing with `myAttendance`, `TimeTastic`.
- **Operational costs:** Django+Channels dyno ($7–25/mo), Postgres ($7), Redis ($3), S3 for face images if persisted ($5), SMS/email OTP if added. QR/JS cost near-zero.
- **Differentiators (as built):** Teacher-toggle face (not auto overwrite), 50 m geofence with frozen denial + live teacher list (rare), active 10s verification + heartbeat (anti-proxy), WebSocket live without native app.
- **Scalability limitations (verified):** `InMemoryChannelLayer` → no horizontal scale; `LocMemCache` → rate-limit per process; `SQLite` → write contention on `AttendanceRecord` unique; no `select_for_update` on `api_verify_complete` (only finalize) → duplicate race relies on DB constraint. Need Postgres + Redis + `select_for_update` for scale.
- **Security requirements for sale:** Must fix P1 logout GET, add `2FA` for teacher admin, `HTTPS/HSTS` already partially, `audit log` for manual marks, `DPDP` consent, `face_image` retention policy, `rate-limit` via Redis not LocMem.
- **Privacy requirements:** DPA for location/face, data residency, delete on request, no continuous tracking claim in marketing.

**Separate research prototype:** Keep as open evaluation tool; productization needs `tenant isolation`, `billing`, `SLA`, `support`.

---

## 13. DEPENDENCY GRAPH

```
Feature → files → APIs → DB → UI → tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create Session
  → frontend: templates/attendance/teacher_dashboard.html (form, JS teacher location 7s)
  → api: POST /attendance/session/create/ (views.create_session)
  → db: AttendanceSession (token, expires_at 30s, teacher FK, classroom/subject FK, face_enabled, radius, teacher lat/lng/accuracy)
  → tests: test_teacher_can_create_session

QR Display + Expiry
  → frontend: teacher_session.html (qr_b64, countdown JS, progress)
  → api: GET /attendance/session/<id>/status/ (expires_at, server_time)
  → db: AttendanceSession.is_expired / is_active
  → realtime: polling 2s + WS group attendance_{id}
  → tests: none dedicated (implicit via scan expired test)

Student Verify Flow (location+scan+verify)
  → frontend: student_verify.html (captureLocation 7s single, startAttempt, jsQR camera, triggerScan reuse cached loc, startVerify 10s, heartbeat 3s, visibilitychange invalidate, frozenOverlay)
  → api: POST /api/attempt/start/ → POST /api/attempt/<id>/scan/ → POST /api/attempt/<id>/complete/ (plus heartbeat/invalidate/location-denied)
  → db: AttendanceAttempt (student, session, attempt_number unique, status OPEN/INVALID/SUCCESS, lat/lng/accuracy, distance, location_verified, face_verified/by_teacher, last_heartbeat, scan_verified_at), LocationDenial (unique session,student), AttendanceRecord (unique session,student, snapshot distance/face)
  → tests: test_location_required, teacher_location_missing, geofence_out_of_range, duplicate_prevention, location_denial_reported

Heartbeat & Stale
  → frontend: heartbeat 3s interval, HB dot
  → api: POST /api/attempt/<id>/heartbeat/ + GET status sweep is_stale>15s → INVALID
  → db: AttendanceAttempt.last_heartbeat
  → tests: none explicit (is_stale logic only via integration)

Face (teacher-only)
  → frontend: teacher_session.html (switch toggle-face, teacher camera facingMode:user + FaceDetector, faceStudentSelect, captureStudentFace → POST teacher-verify-face)
  → api: POST /session/<id>/toggle-face/, POST /session/<id>/teacher-verify-face/ (new), POST /api/attempt/<id>/face/ (legacy student upload, still valid)
  → db: AttendanceSession.face_verification_enabled, AttendanceAttempt.face_verified, face_verified_by_teacher, face_image (TextField base64)
  → tests: test_face_toggle (covers legacy student upload path, not teacher capture)
  → gap: no test for teacher-verify-face

Location Denial
  → frontend: student frozenOverlay → POST /api/location-denied/ → teacher denials red card
  → api: POST /api/location-denied/
  → db: LocationDenial
  → realtime: group_send location_denied
  → tests: test_location_denial_reported

Teacher Live Monitor
  → frontend: teacher_session.html (students_data table, present_count, denialsList, faceQueue, liveFeed, polling 2s, WS onmessage)
  → api: GET status (present_list, denials, face_queue_count, teacher_location)
  → consumers: AttendanceConsumer (AuthMiddlewareStack, _is_allowed)
  → tests: test_unauthorized_teacher_session_access (status 403)

Manual Mark / Finalize / History / Analytics / CSV
  → frontend: teacher_session.html manual modal, finalize form; teacher_history.html (filters, pagination 50), analytics.html (Chart.js)
  → api: POST /session/<id>/manual/, POST /session/<id>/finalize/ (atomic select_for_update), GET teacher_history/student_history (Paginator 50), GET analytics, GET export_csv (UTF-8 BOM)
  → db: AttendanceRecord filter by teacher, Enrollment distinct
  → tests: test_finalize_marks_absent

Auth / Classroom / PWA / Health
  → accounts/views (register/login/logout, rate-limit cache, url_has_allowed_host_and_scheme)
  → classroom/views (create/list/manage, CODE_RE/NAME_RE, Enrollment unique)
  → config/settings (CACHES LocMem, CHANNELS InMemory/Redis, SECURITY headers, LOGGING)
  → templates/base.html (POST logout, a11y, WS? no)
  → static/sw.js (skips /attendance, /ws; PWA manifest)
  → tests: test_open_redirect_protection, test_student_must_be_enrolled

High-risk shared files (see §17): attendance/views.py (~1050 lines touches every flow), attendance/models.py (constraints), student_verify.html + teacher_session.html (critical JS state machine).
```

---

## 14. CHANGE-RISK MODEL

**RED — core attendance/security/database logic; minimize changes, require atomic review + concurrent test:**
- `attendance/views.py` — every QR/location/face/heartbeat state, unique enforcement, `transaction.atomic`, `select_for_update` finalization. **~1050 lines, highest RMCA.** Any edit risks duplicate/P0.
- `attendance/models.py` — `unique_together` for `AttendanceRecord (session,student)` and `AttendanceAttempt (student,session,attempt_number)`, `LocationDenial` unique, `is_stale`, `is_active/expired`. Schema changes need migration.
- `attendance/consumers.py` — WS `attendance_{session_id}` authz; InMemory vs Redis behavior.
- `classroom/models.py` + `accounts/models.py` (User role) — enrollment ownership, teacher limit_choices_to.

**YELLOW — shared / regression risk; changes need integration test:**
- `templates/attendance/student_verify.html` (545 lines JS state machine: idle/scan/verify/success/invalid + location 7s fast path + heartbeat + visibilitychange + jsQR). Recent churn 75f0b38 proves QR expiry regression risk.
- `templates/attendance/teacher_session.html` (teacher controls, camera `facingMode:user`, location 7s, polling 2s, face queue).
- `attendance/utils.py` `haversine_meters` — math correct but accuracy/error handling critical for geofence UX.
- `attendance/urls.py` — 16 routes, token/session param parsing.
- `config/settings.py` — `CACHES LocMem` vs Redis, `CHANNEL_LAYERS` InMemory, `ALLOWED_HOSTS *` in DEBUG, `QR_EXPIRY_SECONDS` etc. Env drift risks.
- `attendance/migrations/*` — 0002/0003 added location/face; next migration must be reversible.

**GREEN — isolated / safe to modify (low regression):**
- `templates/attendance/teacher_dashboard.html`, `student_dashboard.html`, `teacher_history.html`, `student_history.html`, `analytics.html`, `classroom/*.html`, `accounts/login|register.html` — pure display, filters, CSV export formatting (though CSV column `Distance,Face` added recently, safe).
- `static/sw.js`, `static/manifest.json` — PWA shell, skips `/attendance` (verified).
- `config/health.py` — `/health` select 1.
- `attendance/management/commands/seed_demo.py` — idempotent demo seeding.
- `DEPLOY_RENDER.md`, `README.md`, `UPGRADE_NOTES.md` — docs.

**Rule for future feature work:** Touch **GREEN** first, then **YELLOW** with browser tests, never **RED** without staff + security + QA paired review and new `test_concurrency` + `test_location_accuracy`.

---

## 15. TEST COVERAGE GAP ANALYSIS

| Subsystem | Current Tests (verified `attendance/tests.py`, `classroom/tests.py`, `accounts/tests.py`) | Missing Tests | High-Risk Untested Paths |
|---|---|---|---|
| **Session lifecycle** | `test_teacher_can_create_session` (302), `test_finalize_marks_absent` (CLOSED + ABSENT creation) | No test for `EXPIRED` auto (expire_if_needed), no 30s expiry tick, no `finalize` concurrency with two teachers | `EXPIRED→CLOSED` with pending OPEN attempts, clock skew |
| **Student verify flow** | `location_required`, `teacher_location_missing`, `geofence_out_of_range`, `duplicate_prevention`, `face_toggle` (legacy student face upload), `location_denial_reported` | **No test for `teacher-verify-face` (teacher camera path)** — gap after 345c7ff; no test for **fast 7s reuse** (75f0b38); no browser test for jsQR decode, camera permission, `visibilitychange` INVALID, `heartbeat` 15s stale sweep, `retry` new attempt | QR expiry race (location 7s vs 30s window), `scan` with `session=` URL param extraction, `complete` teacher-side face message |
| **Attendance invariants** | `duplicate_prevention` (409), `test_finalize_marks_absent` checks ABSENT creation, unique constraint verified via race `IntegrityError` | No multi-student concurrent `complete` stress (e.g., 20 parallel Clients POST complete) | `unique(session,student)` under load, `select_for_update` only on finalize not on `complete` |
| **Identity / AuthZ** | `test_student_must_be_enrolled (403)`, `test_unauthorized_teacher_session_access (404 teacher, 403 student status)`, `test_open_redirect_protection` | No test for `manual_mark` IDOR with other teacher's `student_id`, no test for `attempt_id` spoof across students, no WS `AttendanceConsumer._is_allowed` test, no `role=student` trying to create session | `WS 4403` close, `accounts/login next` evil.com redirect (covered helper but not POST integration) |
| **Heartbeat / realtime** | None dedicated | No `heartbeat` throttling (60/60), no stale sweep marking INVALID, no `pagehide sendBeacon` | InMemoryChannelLayer single-process vs Redis multi-process, WS fallback polling |
| **Location** | `geofence_out_of_range` (13.1/80.1 → 400), `location_denial_reported` (denials_count 1) | **No test for `accuracy` field**, no test for `distance recompute at complete with latest teacher anchor`, no indoor `±30m` warning path, no `LocationDenial` unique-per-session spam | Haversine edge cases (antimeridian, poles) not triggered, `has_teacher_location` false → `teacher_location_missing` |
| **Face** | `test_face_toggle` (enable, student upload → complete, toggle OFF) via legacy `api_face_verify` | **No teacher-verify-face**, no `face_image` size/ MIME validation test (300k), no `face_verified_by_teacher` propagation to `AttendanceRecord`, no false positive/negative benchmark | Teacher camera permission denial, `FaceDetector` availability fallback |
| **PWA / PWA SW** | None | No offline install test, no skip `/attendance` cache assertion, no `manifest.json` icons validation | Service worker version `sw.115c159bf111.js.gz` staleness |
| **Pagination / history** | None | No `teacher_history?page=2` 50-per-page, no analytics 75% threshold edge, no CSV BOM + escaping | Large `records[:200]` now `Paginator 50` but no test for `page` out-of-range `get_page` |
| **Security** | `test_open_redirect_protection` helper | No `logout GET` CSRF, no `rate-limit` locMem across workers, no `X-Forwarded-For` spoof, no `face_image` XSS, no `DATA_UPLOAD_MAX_MEMORY_SIZE` 2MB overflow | `ALLOWED_HOSTS *` in DEBUG, `DATA_UPLOAD_MAX_MEMORY_SIZE` boundary |

**Overall coverage:** ~11 integration tests (55–60% of RED paths). **Critical missing:** `teacher-verify-face`, WS authz, heartbeat stale, concurrent duplicate, location accuracy, and browser-level `jsQR`/`geolocation` mocks. **Recent QR changes (345c7ff+75f0b38) are only half-covered** — `face_toggle` covers legacy, not current teacher flow, and fast-path reuse has zero test.

---

## 16. DATABASE MODEL (verified via `models.py` + `migrations/` + `python manage.py showmigrations` mental)

**Tables & columns (actual, not assumed):**

- `accounts_user` (extends `auth_user`): `id`, `password`, `last_login`, `is_superuser`, `username` (unique), `first_name`, `last_name`, `email`, `is_staff`, `is_active`, `date_joined`, `role` (teacher/student), `roll_number` (30, nullable), `phone` (15), `avatar` (ImageField). PK `id`.

- `classroom_classroom`: `id` BigAuto, `name` 100, `section` 20, `code` 20 unique, `teacher_id` FK `accounts_user` `limit_choices_to teacher`, `created_at`. `unique_together (name,section)`, ordering.

- `classroom_subject`: `id`, `name` 100, `code` 20 unique, `description`, `created_at`.

- `classroom_enrollment`: `id`, `student_id` FK `accounts_user`, `classroom_id` FK, `roll_number` 30, `enrolled_at`. `unique_together (student, classroom)`, ordering roll_number, username. Index via unique.

- `attendance_attendancesession`: `id` UUID PK, `teacher_id` FK, `classroom_id` FK, `subject_id` FK, `token` 64 unique indexed, `status` (OPEN/EXPIRED/CLOSED) 10, `created_at`, `expires_at` (auto `now+30s` if not set), `closed_at` nullable, `teacher_latitude/lng` nullable Float, `teacher_location_updated_at` nullable DateTime, `teacher_location_accuracy` nullable Float (0003), `face_verification_enabled` Bool default False, `allowed_radius_meters` PositiveInt default 50. Ordering `-created_at`. No FK index beyond.

- `attendance_attendanceattempt`: `id` BigAuto, `student_id` FK, `session_id` FK, `attempt_number` PositiveInt, `status` (OPEN/INVALID/SUCCESS), `created_at`, `last_heartbeat` (auto_add), `scan_verified_at` nullable, `verification_started_at` nullable, `student_latitude/lng` nullable Float, `student_location_accuracy` nullable Float (0003), `distance_meters` nullable Float, `location_verified` Bool, `face_verified` Bool, `face_verified_by_teacher` Bool (0003), `face_image` Text nullable. `unique_together (student, session, attempt_number)`, ordering `-created_at`. FK indexes.

- `attendance_attendancerecord`: `id` BigAuto, `session_id` FK, `student_id` FK, `status` (PRESENT/ABSENT), `method` (QR/MANUAL), `marked_at` auto, `marked_by_id` FK nullable SET_NULL, `student_latitude/lng` nullable Float, `distance_meters` nullable Float, `face_verified` Bool. `unique_together (session, student)` — **the invariant**. Ordering `-marked_at`.

- `attendance_locationdenial`: `id` BigAuto, `session_id` FK, `student_id` FK, `reason` (denied/unavailable/timeout/disabled) 20, `latitude/lng` nullable Float, `created_at` auto. `unique_together (session, student)` ordering `-created_at`.

**Indexes:** `token` `db_index`, `unique_together` combos (implicit unique indexes). No explicit `Gin` or `btree` beyond. No `CHECK` for lat/lng range — validated in view, not DB.

**Migrations:** `0001_initial` (session/attempt/record), `0002_add location/face/denial + allowed_radius + face_enabled + teacher lat/lng`, `0003_add teacher_accuracy, student_accuracy, face_verified_by_teacher, alter face_image help_text`. All applied `python manage.py migrate` OK (verified `Applying … OK`).

**Seed logic:** `attendance/management/commands/seed_demo.py` idempotent: creates `teacher01/teacher123`, `student01..student08 + arjun, priya`, classes `CSE-A-2025, CSE-B-2025`, subjects, 3 finalized sessions for analytics demo.

**Transactions:** `api_verify_complete` → `transaction.atomic get_or_create` Record; `manual_mark` same; `finalize_session` `transaction.atomic select_for_update` on Session.

---

## 17. REALTIME MODEL

**Backend:** `channels` `InMemoryChannelLayer` (dev) / `RedisChannelLayer` if `REDIS_URL` (prod). `AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(attendance.routing.websocket_urlpatterns)))`. `Channel: group `attendance_{session_id}` per session; `group_send type attendance.update data {...}` on `api_verify_complete` (PRESENT), `manual_mark`, `api_update_teacher_location`, `api_toggle_face`, `api_teacher_verify_face`, `api_location_denied` (denied/other), `api_face_verify`.

**Frontend:** `teacher_session.html` opens `new WebSocket((https?'wss':'ws')+'//'+location.host+'/ws/attendance/'+sessionId+'/')`; `onopen → Live via WebSocket`, `onmessage JSON.parse` → `if type attendance_update/location_denied/face_captured → pollStatus()` else `pollStatus`; `onerror/onclose → Polling (WS fallback)`. Additionally **HTTP polling every 2s** via `setInterval(pollStatus,2000)` fetching `session_status_api` (present_list, denials, face_enabled etc.) and patching DOM + `present_count` + table rows. Fallback ensures live even if WS fails (Free Render sleeps, no Redis).

**Heartbeat:** Student `api_heartbeat POST every 3s` while `OPEN`; server `last_heartbeat=now`; sweep stale `>15s` → `INVALID`. Mitigates `blur` exploit (now `visibilitychange`).

---

## 18. PWA MODEL

**Manifest:** `/static/manifest.json` (verified `staticfiles/manifest.json` exists, compressed). `base.html` links `<link rel="manifest" href="/static/manifest.json">` + `theme-color #0f172a`.

**Service worker:** `/static/sw.js` (also hashed `sw.115c159...` in `staticfiles`). Installable, caches static shell but **explicitly skips** `/attendance` and `/ws` (verified in `sw.js` fetch handler: `if (request.url.includes('/attendance') || request.url.includes('/ws')) return fetch(request)`). Prevents stale attendance. `templates/base.html` registers `if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js')`.

**No test for PWA** — gap.

---

## 19. BUGS DISCOVERED (verified from repository, not hypothetical)

- **P0 — QR expiry race (already fixed but root cause documented):** `345c7ff` 3×12s `best-of-3` caused `startAttempt` to block 36s → `is_expired()` at `scan` → `400 QR has expired`. Fixed by `75f0b38` 7s single reuse, but **no regression test** locks it. *Label:* **P0 (was, now fixed — needs test).*
- **P0 — Face bypass via teacher capture before start:** `api_teacher_verify_face` creates an `OPEN` attempt with `face_verified=True` even if student never started location/QR (no enrollment still checked, but no `scan_verified_at` required at capture). If later student location is out_of_range but face already true, `complete` may still succeed for distant student if `location_verified` passes with stale teacher anchor. *Label:* **P1** (design allows pre-verification).
- **P1 — Location accuracy `±30m` still shows 21m confusion:** Teacher/student `±20m` indoors → `distance 21m` correct within error but UX reports “sitting front of laptop”. Current fast 7s single attempt **does not improve accuracy**, only speed — accuracy remains poor indoors. No retry with `maximumAge`. *Label:* **P1** (UX, not correctness).
- **P1 — `api_verify_complete` missing `select_for_update`:** `finalize` uses it, `complete` does not — concurrent `complete` from same student on two devices could race `get_or_create` and rely only on `IntegrityError` 409, which is correct but leaves small window for `SUCCESS` + `INVALID` flip without locking session row. *Label:* **P1**.
- **P1 — `logout_view` GET CSRF:** `require_http_methods(["GET","POST"])` allows `<img src="/accounts/logout/">` forced logout. *Label:* **P1**.
- **P1 — `CACHES LocMem` + `X-Forwarded-For` spoof:** Rate-limit per `ip` taken from first `X-Forwarded-For` token without trusted proxy check → attacker can rotate IP by header. Plus per-process memory not shared across workers. *Label:* **P1**.
- **P1 — Face image retention:** `face_image` TextField retained forever, no purge on `CLOSED`, no consent flag, accessible to any teacher of session. *Label:* **P1** (privacy).
- **P1 — `ALLOWED_HOSTS=['*']` when DEBUG True:** Opens DNS-rebind in dev preview (E2B `*.e2b.app` needs `*` but production correctly locks to `RENDER_EXTERNAL_HOSTNAME` when DEBUG False). *Label:* **P1** (acceptable for dev, still warn).
- **P2 — Teacher camera `facingMode:user` on device without front cam:** `getUserMedia` fails → alert only, no file-upload fallback. *Label:* **P2**.
- **P2 — `teacher_location_accuracy` not returned to student in `session_status_api`:** Student sees `teacher_lat/lng` but not `±Xm`, so cannot diagnose distance error root. *Label:* **P2** (now teacher badge shows, student not).
- **P2 — Pagination missing test:** `teacher_history` uses `Paginator.get_page` (safe) but no test for `?page=999` out-of-range.
- **P3 — `templates/404.html`/`500.html` branding but no `handler404` custom test.**
- **P3 — `staticfiles` hashed filenames (`sw.115c...`) not purged on new deploy may cache old JS without location fast path until hard reload.**

---

## 20. REGRESSION RISKS (for future prompts)

- **RED regression risk if modifying `attendance/views.py`:** Any change to `api_start_attempt` token extraction (`session=` URL parsing) risks breaking external QR link decode; changing `api_scan` expiry check (`is_expired` at scan time) risks re-introducing post-expiry `PRESENT`.
- **YELLOW risk touching `student_verify.html`:** JS `state` machine + heartbeat interval + `visibilitychange` timing is fragile; re-adding a `prep` gap without adjusting `QR_EXPIRY_SECONDS` re-breaks QR window (as happened).
- **YELLOW risk changing `haversine_meters`:** Slight radian error → geofence systematically 5% off; no unit test for haversine known distance (e.g., 0,0 to 0,1 ≈111km).
- **RED risk disabling `LocationDenial` unique:** Removing `unique(session,student)` would allow spam.
- **RED risk altering `AttendanceRecord.unique`:** Removing DB constraint would silently allow duplicate PRESENT without 409.
- **PWA risk:** Caching `/attendance/verify/` would serve stale token after expiry — `sw.js` skip must stay.
- **Migration risk:** Adding non-nullable field without default breaks existing `db.sqlite3`; 0003 correctly used `nullable`.

---

## 21. RECOMMENDED IMPLEMENTATION ORDER (for future feature work, not this pass)

**Do-not-implement now — ordered backlog for next prompts (after this audit is accepted):**

1. **P0 — Lock location fast-path with tests (do not re-introduce 30s):** Add Playwright test `location 7s not 30s` (mock `navigator.geolocation` latency) + unit test for `haversine` + `is_expired` edge 29.9s vs 30.1s. *Why first:* prevents QR expiry regression we just fixed.
2. **P0 — Add missing `teacher-verify-face` integration tests + retention policy:** Test `teacher capture → student complete` flow, assert `face_verified_by_teacher`; add management command to purge `face_image` >7d after `CLOSED` and write retention doc.
3. **P1 — Fix logout CSRF (POST only) + rate-limit Redis:** Change `logout_view` to `@require_POST` with form in `base.html` already POST; move `CACHES` to `Redis` when `REDIS_URL` present, validate `X-Forwarded-For` against `RENDER` trusted proxies.
4. **P1 — Geofence UX hardening (no continuous tracking):** Keep single-shot 7s, add `maximumAge:30000` fallback, surface `teacher accuracy` to student in `session_status_api.teacher_accuracy`, add teacher manual radius override UI (already 10–500) with warning.
5. **P1 — Heartbeat/WS coverage:** Add concurrency test 20 parallel `complete`, add WS consumer test `AttendanceConsumer._is_allowed`, benchmark InMemory vs Redis.
6. **P2 — PWA & pagination tests:** Assert `sw.js` skips `/attendance`, assert `Paginator` out-of-range, add `analytics` 75% low-attendance edge.
7. **P3 — Research instrumentation (if pursuing paper):** Add anonymized metrics table `SessionMetrics(distance_histogram, accuracy_cdf, completion_latency)` — opt-in, no PII.

**Rule:** Never bundle P0+P1 in same PR; keep RED changes minimal per PR.

---

## APPENDIX — VERIFICATION COMMANDS RUN

```
find . -type f | sort
cat requirements.txt / runtime.txt / render.yaml / build.sh / Procfile
cat config/settings.py (300+ lines)
cat accounts/models.py / views.py
cat classroom/models.py / views.py
cat attendance/models.py / utils.py / routing.py / consumers.py
head -n 300 attendance/views.py ; grep -rn "def " attendance/views.py
cat attendance/urls.py
ls -l attendance/migrations/ ; cat 0001..0003
find templates -type f | sort ; head base.html / login.html / student_verify.html / teacher_session.html
ls -R tests | cat attendance/tests.py (11 tests)
python manage.py check ; python manage.py test attendance --verbosity=0 (OK)
git log --oneline --graph --all -15 ; git diff HEAD~1 --stat ; cat README.md / UPGRADE_NOTES.md / DEPLOY_RENDER.md
```

**Attestation:** Every section above traces to a file/command listed. No code was modified during this audit pass as instructed. Future prompts should treat `75f0b38` as baseline; any deviation must be diffed against the `AUDIT_REPORT.md` invariants.

