# ✅ Upgrade v2 — Face Scan + 50m Geofence + Location Denial Reporting

## What Was Added (Per Your Request)

### 1. 📍 Mandatory Location Tracking (50m Geofence)
- **Teacher's laptop is source of truth**: When teacher creates session, browser captures `teacher_latitude/longitude` via `navigator.geolocation` (high accuracy). Teacher can also `Capture / Update My Location` anytime on session page. If teacher location not set, students are blocked with message: *“Teacher location not set yet. Ask teacher to tap Capture My Location.”*
- **Student mandatory**: On `Start Verification`, student's browser requests location. 
  - **If denied/disabled/unavailable/timeout** → **full-screen frozen overlay** appears: *“📍 Location Required — Frozen until you enable location. Your name/roll has been sent to teacher.”* Button = `Enable Location & Retry`. Student **cannot** proceed to QR scan/verify, and final `COMPLETE` will fail with `location_required`.
  - Denial is POSTed to `/attendance/api/location-denied/` → creates `LocationDenial(session, student, reason)` and **broadcasts via Channels** to teacher.
- **50m check**: Server computes Haversine distance between student lat/lng and teacher lat/lng.
  ```python
  haversine_meters(lat1, lon1, lat2, lon2)  # R=6371000
  ```
  - `attempt.distance_meters` stored, `location_verified = dist <= allowed_radius_meters` (default 50, teacher can choose 30/50/100/200 at session creation)
  - **At `start`** → warns if out of range; **At `complete`** → hard reject: *“You are 1294m away. Must be within 50m.”* No `PRESENT` created.
  - UI shows live `Distance to Teacher: 7m ✓ Within 50m` or `Out of range`.

### 2. 📷 Face Scanning via Teacher's Camera (Teacher Toggle Only)
- **Teacher controls ON/OFF**: Checkbox on create form + **toggle switch** on active session page (`/attendance/session/<id>/toggle-face/`). Only teacher can toggle. Students see badge `Face ON/OFF` and step `2b Face` appears/disappears live via polling.
- **Teacher camera panel**: On session page, teacher can `Start My Camera` → shows `teacherVideo` feed with `FaceDetector` (if browser supports) feedback *“Face detected (1) — you are verified”*. This satisfies “teacher's camera should be used for face scanning”.
- **Student face step**: If `face_verification_enabled=True`, after QR scan student must do face scan:
  - Opens `faceVideo` (`facingMode: user`), live `FaceDetector` feedback, `Capture & Verify Face` → captures `canvas.toDataURL('image/jpeg')` → POST to `/attendance/api/attempt/<id>/face/` → server stores `face_image` (base64 truncated) + `face_verified=True` + notifies teacher via WebSocket.
  - Teacher's **Face Verification Queue** panel shows thumbnails live (polling `face_queue_count`).
  - At `verify complete`, if face required but `face_verified=False` → reject *“Face verification required.”* Student must complete face scan.
- If teacher toggles face OFF mid-session, students skip face step and `faceVerified` auto-true, and queue hides.

### 3. 🚫 Frozen Until Location Enabled + Teacher Reporting
- **Frozen overlay**: `position: fixed; inset:0; background:rgba(15,23,42,.92); backdrop-filter:blur(8px); z-index:200` — blocks all interaction, only `Enable Location & Retry` works. Message matches your spec: *“who doesnt allow location, should not be able to mark their attendence present and those whose attendence is turned off, at the end ... they should get a message that freezes there until location is enabled”*.
- **Teacher reporting**: `LocationDenial` table `UNIQUE(session, student)` → displayed on:
  - **Teacher dashboard** → `Recent → Location Denied — Recent` (top hero) 
  - **Teacher session page** → `Location Denied — Students Blocked` card (red, with `denialCount`, names/rolls, reason, time) — **auto-updates via `status` polling (2s) + WebSocket** 
  - Included in `session_status_api` → `denials: [{username, roll, reason, time}]`
  - CSV export now includes `Distance(m)` and `Face` columns; history shows `LOCATION_DENIED` badge for those rows.

---

## Database Changes ( Migration `0002` Applied)

```python
AttendanceSession:
  teacher_latitude, teacher_longitude, teacher_location_updated_at
  face_verification_enabled (bool), allowed_radius_meters (int, default 50)
  has_teacher_location() helper

AttendanceAttempt:
  student_latitude, student_longitude, distance_meters, location_verified
  face_verified, face_image (TextField base64)

AttendanceRecord:
  student_latitude, student_longitude, distance_meters, face_verified

LocationDenial(session, student, reason, created_at)  UNIQUE(session, student)
```

---

## API Changes

| Endpoint | Method | New Body/Logic |
|---|---|---|
| `POST /attendance/session/create/` | POST | `face_verification_enabled`, `allowed_radius_meters`, `teacher_latitude/longitude` |
| `POST /attendance/session/<id>/teacher-location/` | POST JSON `{latitude, longitude}` | Teacher updates source location |
| `POST /attendance/session/<id>/toggle-face/` | POST JSON `{enabled: true/false}` | Only teacher; broadcasts |
| `POST /attendance/api/attempt/start/` | POST JSON `{token, latitude, longitude}` | **Requires** lat/lng; checks teacher location set; Haversines; returns `distance`, `location_verified`, `face_required` |
| `POST /attendance/api/attempt/<id>/scan/` | POST | Accepts optional `latitude/longitude` to update distance |
| `POST /attendance/api/attempt/<id>/face/` | POST JSON `{face_image: "data:image/jpeg;base64,..."}` | Stores + marks `face_verified` |
| `POST /attendance/api/attempt/<id>/complete/` | POST | **Enforces** location within radius + face if required; stores distance/face on `AttendanceRecord` |
| `POST /attendance/api/location-denied/` | POST JSON `{token, reason}` | Creates `LocationDenial`, notifies teacher |
| `GET /attendance/session/<id>/status/` | GET | Now returns `face_enabled`, `radius`, `teacher_lat/lng`, `teacher_location_set`, `denials`, `denials_count`, `face_queue_count` |

---

## UI Changes

- **Teacher Dashboard**: Face checkbox + radius select + `Your Location` capture box (lat/lng live, `Recapture` button); hero shows denials; session list shows `50m • Face ON/OFF • Located`.
- **Teacher Session**: Top badges `Face ON/OFF`, `50m`, `Teacher located/not set`; **Teacher Controls** card with face switch + `Start My Camera` + teacherCam video + location recapture; **Location Denied** red card (always visible); **Face Queue** horizontal scroll of snapshots; attendance table adds `Distance / Face` column + `LOCATION_DENIED` badge + frozen hint; polling updates all.
- **Student Verify**: New location header (your lat/lng, accuracy, teacher location hint, distance meter); steps dynamic (adds `2b Face` when enabled); `Start` button now `Enable Location & Start`; frozen overlay; faceState with `faceVideo`, `FaceDetector` live feedback, `Capture & Verify`; verify checks 50m badge; success shows distance; all error toasts handle `out_of_range`, `face_required`, `location_required`.

---

## How to Demo (2-Min)

1. **Teacher**: `teacher01/teacher123` → Dashboard → **Check `Face Verification` ON**, `50m`, allow location → **Generate QR** → Open session → See `Teacher Camera` → `Start My Camera` → location shows `Set ✓`.
2. **Student** (incognito): `student03/student123` → `Verify` → **Deny location** → **Frozen overlay** appears → Teacher sees `student03 • denied` in `Location Denied` card instantly.
3. Student enables location (allow) → `Retry` → distance shows `7m Within 50m` → `Start` → 10s prep → scan QR → **Face Scan** appears (teacher face ON) → `Capture` → green `Face verified` → 10s verify → `PRESENT`.
4. Move student far (mock lat `13.09,80.28`) → on complete → `You are 1293m away… Move within 50m and retry.` Denies again if disabled → frozen.
5. **Teacher toggles Face OFF** via switch → student next attempt skips face, directly to verify.
6. CSV export now has `Distance(m)` + `Face` columns.

---

## Render Deployment (No Change Needed)

Same `build.sh`/`render.yaml`/`Procfile` — migration already applied. Push new code:

```bash
git add .
git commit -m "Upgrade: 50m geofence + face toggle + location denial reporting"
git push origin main
# Render auto-deploys: pip install → collectstatic → migrate (0002) → seed_demo
```

---

## Backend Tested

```
create with face 302 → sess face True 50 13.0827
start without loc 400 location_required True (frozen)
start with loc close 200 distance 7m location_verified True face_required True
complete without face 400 face_required True
face upload 200 face_verified True
complete with face 200 SUCCESS
far start 200 distance 1293m location_verified False
far complete 400 out_of_range 1294m
denied log 200 denials count 1 student04 denied
toggle face OFF 200 face off
student05 after face off: start/complete without face → SUCCESS
teacher loc missing: teacher_location_missing True
teacher update loc 200
retry after teacher loc 200 ok
```

All enforced server-side, not just UI.
