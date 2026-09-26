# Smart QR-Based Classroom Attendance System — Django

> **A secure, real-time web-based classroom attendance system where teachers create temporary QR sessions and enrolled students authenticate, scan, and actively verify attendance — with server-side authorization, expiry, heartbeat, retry, atomic constraints, and realtime sync.**

![Django](https://img.shields.io/badge/Django-6.x-%23092E20) ![Python](https://img.shields.io/badge/Python-3.13-blue) ![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ One-Sentence Pitch

A teacher creates a **30-second QR for a class/subject**; many enrolled students use that same QR, but each can be marked **once**; identity is the **authenticated account** (not client `student_id`); attendance needs **10s prep → QR validation → 10s verification** with **3s heartbeat** and **server-authoritative expiry**; duplicates are blocked by `UNIQUE(session, student)` and raced writes are atomic.

### Judge's 30s Pitch

> “Our system digitizes attendance with temporary QRs: a teacher creates a 30-sec QR for a class/subject, multiple enrolled students use it. Each student's identity is their login, and they must finish an active verification before being marked present. The backend enforces enrollment, expiry, duplicates & atomic transactions, while heartbeats and WebSocket live updates make it reliable. After finalization, absentees are marked and analytics + CSV reports are ready.”

---

## 🏗️ Architecture

```
Teacher Dashboard ──Create Session──► AttendanceSession (30s token, OPEN)
                                         │
              ┌───────────────────────────┼───────────────────────────┐
              ▼                           ▼                           ▼
         Student A                    Student B                    Student C
              │                           │                           │
              └───────────────────────────┼───────────────────────────┘
                                          ▼
                                    Authentication
                                          │
                                     Enrollment check
                                          │
                                      OPEN Attempt (attempt_number)
                                          │
                                    10s Preparation (heartbeat 3s)
                                          │
                                       QR Scan (server validation)
                                          │
                                    10s Verification (OPEN stays OPEN)
                                          │
                                       SUCCESS → PRESENT (QR)
                                          │
                         ┌────────────────┴────────────────┐
                         ▼                                 ▼
                      SQLite                           Channels WebSocket → Teacher Live (PRESENT X/N)
                         ▼
                     Finalize → ABSENT for remaining, Analytics, CSV
```

---

## 🔐 Security & Correctness

| Threat | Mitigation |
|---|---|
| Unauthenticated scan | `login_required`, session cookie HttpOnly |
| Forged `student_id` | Server derives `request.user` — never trusts client ID |
| Cross-student attempt tampering | `AttendanceAttempt` filtered by `student=request.user` |
| Not enrolled → scan | `Enrollment` check before `OPEN` or `SUCCESS` |
| Expired QR reuse | `now >= expires_at` server time; scan at 29.9s valid, 30.1s rejected; verification after valid scan may finish |
| Duplicate PRESENT | `UNIQUE(session, student)` + `select_for_update` / `get_or_create` atomic |
| Race duplicate | DB constraint catches second concurrent insert → 409 |
| No blur-exploit | Uses `visibilitychange` + `pagehide`, **not** `blur`; heartbeat backstop 15s; stale sweep |
| Finalized → mutate | `CLOSED` blocks manual/finalize |
| CSV/WebSocket authz | Teacher-only queryset + channel group `attendance_{session_id}` with `AuthMiddlewareStack` |

**Honest limit:** “Authenticated account-bound attendance with active verification and proxy-risk reduction, not perfect physical identity proof.” If A logs in as B, the app sees B — same as any web app.

---

## 🧩 Core Modules (No Compromise)

### 1. Teacher Flow
- Create session: picks Class + Subject → token `secrets.token_urlsafe(32)` → `expires_at = now+30s` → QR `https://app/scan?session=TOKEN` (also in-app scanner)
- Dashboard shows **QR**, **30s countdown** (server time `expires_at`), **PRESENT X/N** live
- Manual mark: `PRESENT/MANUAL`, blocked if already present; after expiry needs explicit confirm; before expiry direct
- Finalize: `OPEN/EXPIRED → CLOSED`, creates `ABSENT` for every enrolled without `PRESENT`; `PRESENT` never downgraded
- History with filters (class/subject/date/status/method), Analytics (overall %, avg, per-student, low < 75%), CSV export (UTF-8 BOM, proper escaping)

### 2. Student Flow
- Detects active sessions for enrolled classes
- Two entry points: phone camera opening link, or **SCAN ATTENDANCE** in-app
- If not logged in → login → `next=/attendance/verify/?session=TOKEN`
- **Active verification lifecycle:** `OPEN → (10s prep) → scan → (10s verification, still OPEN) → SUCCESS → PRESENT`
- Attempt table `UNIQUE(student, session, attempt_number)` → many retries via `OPEN→INVALID` then new `OPEN`; final table `UNIQUE(session, student)`
- Valid scan before expiry may finish even if QR expires mid-verification

### 3. Realtime & Heartbeat
- **WebSocket** `ws/attendance/<session_id>/` via **Django Channels** (InMemory for dev) + `group_send` on each `PRESENT`
- HTTP polling every 2s as fallback
- **Heartbeat** POST every 3s while `OPEN`; server stores `last_heartbeat` (server time); sweep marks stale (>15s) as `INVALID`; short blips tolerated

### 4. Interruption
- `visibilitychange` + `pagehide` (not `blur`) → `INVALID` if left during prep/scan/verify → retry gives new attempt
- Browser back/close handled via `sendBeacon`

### 5. PWA
- `manifest.json` + `sw.js` (installable)
- Service worker **does not** cache `/api/*`, `/ws/*`, `/socket.io/*` — live attendance never stale

---

## 🛠️ Tech Stack

- **Frontend:** Django Templates + vanilla JS, CSS variables, Space Grotesk + Plus Jakarta Sans, Font Awesome, html5 `jsQR` for in-browser decode, Chart.js for analytics
- **Backend:** Python 3.13, Django 6.1, Channels 4, Daphne, SQLite + `better-sqlite` semantics via Django ORM, `qrcode[pil]`
- **Auth:** Django `AbstractUser` (`role=teacher|student`, `roll_number`), session cookies `HttpOnly`, `SameSite=Lax`, `pbkdf2`
- **QR:** `qrcode` → base64 PNG, payload = absolute URL `/attendance/verify/?session=TOKEN`

---

## 📂 Project Structure

```
smart_qr_attendance/
├── config/               # settings, urls, asgi/wsgi (Channels)
├── accounts/             # Custom User, login/register, role guard
├── classroom/            # ClassRoom, Subject, Enrollment
├── attendance/           # Session, Attempt, Record + views, consumers, routing
│   └── management/commands/seed_demo.py
├── templates/
│   ├── base.html         # Glass navbar, gradient hero, message toasts
│   ├── accounts/
│   ├── attendance/       # teacher_dashboard, teacher_session, student_dashboard, verify, history, analytics
│   └── classroom/
├── static/
│   ├── manifest.json
│   └── sw.js             # skips /attendance & /ws
├── manage.py
└── requirements.txt
```

---

## 🚀 Quick Start

```bash
# 1. Create venv & install
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Migrate & seed demo
python manage.py migrate
python manage.py seed_demo
# creates:
#   teacher01 / teacher123
#   student01..student08, arjun, priya / student123
#   CSE-A-2025, CSE-B-2025
#   CS201, CS301, CS302, CS401
#   3 finalized sessions for analytics

# 3. Run (Daphne for Channels, or runserver for dev)
python manage.py runserver 0.0.0.0:8000
# or with Daphne:
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Visit http://127.0.0.1:8000  → redirects to /dashboard/
```

### Manual Setup (no seed)

```bash
python manage.py createsuperuser  # choose role teacher
python manage.py shell
# then in shell create ClassRoom, Subject, enroll students via UI at /classroom/
```

---

## 🧪 Try The Flow

1. **Teacher:** login `teacher01 / teacher123` → Dashboard → pick `CSE-A-2025` + `CS201` → **Generate 30s QR** → open session page → see countdown + `PRESENT 0/N` → keep tab open (WebSocket live).
2. **Student (new tab/incognito):** login `student01 / student123` → Dashboard shows **Active Sessions** → **Start Verification** → 10s prep → camera scans teacher QR (or paste token) → 10s verification (stay on page) → **SUCCESS → PRESENT**.
3. **Teacher tab:** count becomes `1/N` instantly + toast + row turns green. Try scanning again with same student → `Already marked present (409)`.
4. **Post-expiry:** let QR expire → **Mark Present** manually → modal asks confirm → `PRESENT/MANUAL`.
5. **Finalize:** teacher clicks **Finalize & Mark Absent** → remaining become `ABSENT` → check **History** + **Analytics** → **Export CSV**.

---

## 🔌 Key URLs

| Path | Role | Purpose |
|---|---|---|
| `/accounts/register/` | Anonymous | Choose teacher/student |
| `/accounts/login/?session=TOKEN` | Anonymous | Preserves QR pending |
| `/dashboard/` | Auto | Router → teacher or student |
| `/attendance/teacher/` | Teacher | Create QR, recent sessions |
| `/attendance/session/<uuid>/` | Teacher | QR, countdown, live list, manual, finalize |
| `/attendance/session/<uuid>/status/` | Teacher/Enrolled | Polling JSON `present_count`, `present_list` |
| `/attendance/verify/?session=TOKEN` | Student | 10s prep → scan → 10s verify |
| `/attendance/scan/?session=TOKEN` | Student | Phone-camera redirect (preserves login) |
| `/attendance/api/attempt/start/` | Student | `POST {token}` → `OPEN` attempt |
| `/attendance/api/attempt/<id>/scan/` | Student | Validate token vs session |
| `/attendance/api/attempt/<id>/heartbeat/` | Student | Every 3s |
| `/attendance/api/attempt/<id>/complete/` | Student | After 10s → `SUCCESS → PRESENT` atomically |
| `/attendance/teacher/history/` | Teacher | Filters + table |
| `/attendance/teacher/analytics/` | Teacher | Charts, low <75% |
| `/attendance/teacher/export/` | Teacher | CSV UTF-8 BOM |
| `/ws/attendance/<uuid>/` | Authed | Channels group `attendance_{id}` |

---

## 🗃️ Data Model Highlights

```python
ClassRoom(code unique, teacher FK, name+section unique)
Subject(code unique)
Enrollment(student FK, classroom FK)  UNIQUE(student, classroom)

AttendanceSession(id uuid, teacher, classroom, subject, token unique, status OPEN/EXPIRED/CLOSED, expires_at=now+30s)
AttendanceAttempt(student, session, attempt_number, status OPEN/INVALID/SUCCESS, last_heartbeat)  UNIQUE(student, session, attempt_number)
AttendanceRecord(session, student, status PRESENT/ABSENT, method QR/MANUAL)  UNIQUE(session, student)
```

---

## 🎨 UI Notes

- No CSS framework build — pure modern CSS with gradients, glass, `Space Grotesk` headings, rounded 20px cards, responsive grids.
- Teacher QR card has **countdown 30→0**, progress bar, copy/print/PNG, expired banner, fullscreen for projector.
- Student verification shows **4 steps**, timers, live camera with `jsQR`, manual token fallback, heartbeat dot, confetti on success.
- All tables use `PRESENT` (green), `ABSENT` (red), `PENDING` (muted), `MANUAL` (dark) badges.

---

## ⚙️ Settings Knobs (`config/settings.py`)

```python
QR_EXPIRY_SECONDS = 30
PREPARATION_SECONDS = 10
VERIFICATION_SECONDS = 10
HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TIMEOUT_SECONDS = 15
```

---

## 🧹 Maintenance

- Expired `OPEN` sessions are auto-marked `EXPIRED` on access (dashboard, session view, status API).
- Stale `OPEN` attempts (>15s no heartbeat) are swept to `INVALID` on status poll and heartbeat.
- `CLOSED` sessions are immutable.

---

## 📜 License

MIT — use for college projects, demos, or production with proper secret key & DB.
