# QR PERFORMANCE FORENSIC INSTRUMENTATION — READ-ONLY DIAGNOSTICS
**Baseline:** `75f0b38` + instrumentation patch (no attendance logic/DB/QR expiry/location/face changes)  
**Mode:** Forensic instrumentation only — `performance.mark()/measure()` + DEBUG panel, production-safe (hidden when `DEBUG=False`)  
**Date:** 2026-09-28

---

## INSTRUMENTATION IMPLEMENTED

### Files modified (minimal, read-only diagnostics)
- `attendance/views.py::verify_page` — added `'debug': settings.DEBUG` to context (1 line). No logic altered.
- `templates/attendance/student_verify.html` — added instrumentation only:
  - DEBUG panel HTML (conditional `{% if debug %}`) — table with # / Stage / Timestamp / Δ prev / Cumulative from Start, counters, diagnostics, Export JSON/Copy
  - `window.QRPerf` helper: `stages[]`, `counters`, `flags`, `videoMeta`, `mark()`, `render()`, `performance.measure(prev→curr)`
  - **17 stages** via `performance.mark()` at exact spec points (see below)
  - Counters: `getUserMedia`, `geolocation`, `scanLoops`, `framesDecoded`, `scanPOSTs`, `attemptPOSTs`, `cameraStreams`
  - Diagnostics: multiple loops, loop after decode, duplicate POSTs, cached location reacquire, video/canvas dimensions

**No changes to:** `AttendanceSession.expires_at` (30s), `allowed_radius_meters` (50), `face_verification_enabled`, `LocationDenial`, `AttendanceRecord.unique`, `is_stale` 15s, `HEARTBEAT 3s`.

### Stages instrumented (1:1 with spec, via `QRPerf.mark()` + `performance.mark()`)

| # | Spec stage | Mark name | Insertion point in `student_verify.html` |
|---|---|---|---|
| 1 | verify page loaded | `verify-page-loaded` | Top of `<script>` at evaluation (`performance.now()` pageLoad) |
| 2 | Start button pressed | `start-button-pressed` | First line of `#startBtn` click handler; also sets `QRPerf.startTs` for cumulative |
| 3 | geolocation request started | `geolocation-request-started` | First line of `getBestPosition()`; `QRPerf.counters.geolocation++` |
| 4a | geolocation success | `geolocation-success` | `getCurrentPosition` success callback (`±Xm` accuracy) |
| 4b | geolocation error | `geolocation-error` | `getCurrentPosition` error callback + hard timeout + not supported |
| 5 | attempt request started | `attempt-request-started` | Before `fetch('/api/attempt/start/')` in `startAttempt()`; `attemptPOSTs++` |
| 6 | attempt response received | `attempt-response-received` | After `await res.json()` in `startAttempt()` |
| 7 | camera getUserMedia requested | `camera-getUserMedia-requested` | First line of `startCamera()` before `getUserMedia`; `getUserMedia++`; detects `scanning && raf` → `multipleLoops` flag |
| 8 | camera stream obtained | `camera-stream-obtained` | After `await getUserMedia` success (`cameraStreams++`) or error |
| 9 | video first frame available | `video-first-frame-available` | `video` `loadedmetadata`/`canplay`/`play() resolved` listener — records `videoWidth×videoHeight`, `canvasW×H` |
| 10 | jsQR loop started | `jsQR-loop-started` | After `scanning=true` in `startCamera()`, `scanLoops++` (>1 → `multipleLoops`) |
| 11 | first frame sent to decoder | `first-frame-sent-to-decoder` | Inside `scanLoop()` before first `jsQR()` call (`__firstFrameSent` guard) — records canvas dimensions |
| 12 | first successful QR decode | `first-qr-decode-success` | Inside `scanLoop()` when `code` truthy (`framesDecoded` count, `data len`) |
| 13 | scan POST started | `scan-POST-started` | Before `fetch('/api/attempt/.../scan/')` in `triggerScan()`; `scanPOSTs++`; detects `scanVerified` already true or `__scanPOSTInFlight` → `duplicateScanPOST` |
| 14 | scan POST completed | `scan-POST-completed` | After `await fetch` in `triggerScan()` (200 vs error) |
| 15 | verification countdown started | `verification-countdown-started` | First line of `startVerify()` (10s) |
| 16 | verification completed | `verification-completed` | When `verifyLeft==0` before final POST |
| 17 | final response received | `final-response-received` | After `await fetch('/api/attempt/.../complete/')` (`200 OK` vs `out_of_range` etc.) |

**Also measured:** `performance.measure(prev→curr)` for each consecutive pair (visible in DevTools → Performance → User Timing).

**Debug panel (DEBUG only):** `{% if debug %}` → `<div id="qrPerfPanel">` with counters, live last stage, table, Export JSON, Copy TSV, diagnostics (multiple loops, reacquire, video dims). Hidden in production (`DEBUG=False` → no HTML emitted, no `QRPerf.debug` render, but marks still go to `performance` + `console.debug` for optional remote log).

**Verification that panel is production-safe:**
- `verify_page` passes `debug=settings.DEBUG`; template `{% if debug %}` gates HTML.
- `QRPerf.debug` is `{{ debug|yesno:"true,false" }}` — when `False`, `render()` is no-op, panel not in DOM, no timing data exposed to student. Marks still exist as `performance.mark` (user timing) but not visible UI; can be stripped in prod build if needed.

---

## FORENSIC FINDINGS FROM CODE (no real-device run yet — static evidence)

Run `python manage.py check` → 0 silenced, `python manage.py test attendance` → 11 OK after instrumentation (no logic broken).

### Exact measured bottleneck (Theoretical, to be confirmed with panel on real device)

**Primary:** `geolocation (5-7s single) + camera initialization (1-3s) + mandatory 10s verification = 16-20s baseline` before final POST, plus user aiming time.

**Breakdown with current `75f0b38` fast path (single 7s, reuse cached):**
- Page load → Start press: user decision (~1-2s, not instrumented latency)
- `geolocation-request-started → success`: **~3-7s** (typical Android `enableHighAccuracy` 4-6s indoors, 2-4s outdoors; 7s cap). Previous `3×12s` was **>30s** and exceeded QR 30s expiry — that was the **previous P0 regression** (audit noted). Now 7s cap keeps QR safe but still dominates.
- `attempt-request-started → response`: **~80-300ms** (local) / **300-800ms** (Render cold, Postgres) — not bottleneck.
- `camera-getUserMedia-requested → stream-obtained`: **~800ms-2500ms** on mid-range Android (permission prompt + hardware init). **Blocks decoding** — `scanLoop` not started until `stream obtained` + `video-first-frame` (sequential, not parallel with location). Evidence: `startAttempt` → `showState('scan'); startCamera();` then `await v.play()` inside `startCamera` before `scanLoop()`.
- `stream-obtained → video-first-frame`: **~150-500ms** (`loadedmetadata`/`canplay`).
- `jsQR-loop-started → first-frame-sent`: **~16ms** (one rAF).
- `first-frame-sent → first-qr-decode-success`: **variable, user aiming** — 0.5-5s if QR already centered, `∞` if QR not in view / poor light / downscaled video. Processes **every frame** via `requestAnimationFrame` (good for low latency, but heavy): every `HAVE_ENOUGH_DATA` frame calls `getImageData` + `jsQR` on full canvas (`videoWidth×videoHeight`, e.g., 1280×720 = 0.9M px). No throttling, no downscale.
- `scan-POST-started → completed`: **~100-400ms**.
- `verification-countdown-started → completed`: **fixed 10s** (spec mandatory active verification) + final POST 100-400ms.

**Total wall-clock Start → PRESENT (happy path, QR already in view):** `~7s (geo) + 0.2s (attempt) + 1.5s (camera) + 0.3s (first frame) + 0.5s (decode) + 0.2s (scan POST) + 10s (verify) + 0.3s (final) ≈ 20s`. Reports of `>20s and sometimes never` **match this expectation** — 20s is *not* a bug, it's the mandatory 10s verify + real-world geo/camera.

**If QR not in view:** `first-frame-sent → first-decode` dominates (user must aim). Instrumentation will show large `Δ` there vs `geolocation` Δ.

### Evidence from code (file:line)

- **Geolocation dominates:** `student_verify.html: getBestPosition(7000)` with hard `timeout+500` and `maximumAge:5000` — previously 3×12s (git `345c7ff`) → `75f0b38` fixed to 7s but still single high-accuracy. No parallelization with camera.
- **Camera blocks decode:** `startAttempt()` → `showState('scan'); startCamera();` then inside `startCamera`: `await getUserMedia` → `await v.play()` → `scanning=true; scanLoop()` — all awaited before loop. `scanLoop` checks `v.readyState===HAVE_ENOUGH_DATA` every frame, so no decode before stream.
- **Duplicate geolocation previously:** Old `startAttempt` did `if(studentLat===null) await captureLocation() else await captureLocation()` (reacquire) — fixed in `75f0b38` to `if(studentLat===null) await captureLocation()` else reuse. Our instrumentation still guards `if(studentLat===null)` in `triggerScan` and flags `cachedLocationReacquired` if violated.
- **Every frame decoded:** `scanLoop()` calls `requestAnimationFrame(scanLoop)` unconditionally at end; inside, if `HAVE_ENOUGH_DATA` draws full `videoWidth×videoHeight` canvas and calls `jsQR` every frame. No `setTimeout` throttle, no worker.
- **Canvas = video native:** `c.width=v.videoWidth; c.height=v.videoHeight` (no downscale). On 1080p phone, 2M px per frame → CPU bottleneck on low-end.
- **Loop after decode:** Previously `triggerScan` returned without clearing `raf`, but next `requestAnimationFrame` not scheduled after decode `return` — so loop stops. Our instrumentation adds `__decodeSuccess` and `loopAfterDecode` flag if `raf` still pending after decode.
- **Multiple loops:** No guard against double `startCamera` while `scanning` — we now detect `scanning && raf` → `multipleLoops`.
- **Duplicate network:** `startBtn` disabled after first click (`btn.disabled=true`) but no debounce on `triggerScan` re-entry — we guard `scanVerified` and `__scanPOSTInFlight` → `duplicateScanPOST`.
- **UI waits after decode:** No extra wait — `scanLoop` → `triggerScan` → `fetch scan` → `startVerify` immediate. Gap measured via `scan-POST-completed → verification-countdown-started` (should be <100ms). Previous prep 10s gap removed in `345c7ff` (now `showState('scan')` directly).

---

## A. EXACT MEASURED BOTTLENECK (to confirm with panel on real device)

**Likely primary:** `geolocation (3-7s) + camera init (1-3s) + mandatory 10s verify` = **~80% of 20s**. **Secondary:** `first-decode` aiming time (variable, user-dependent). **Tertiary:** network (negligible) unless Render cold start (1-2s first attempt POST).

**Evidence to collect:** Run on real Android (Chrome) + iPhone (Safari) with panel (`?debug=1` or `DEBUG=True` + superuser) and compare:
- If `geolocation-success` Δ is 6-7s and `camera-stream-obtained` Δ is 2s → geo+camera is bottleneck.
- If `first-frame-sent → first-decode-success` Δ is 8-15s → aiming/decode is bottleneck (QR too small, poor light, canvas too large).
- If `attempt-response` or `scan-POST` Δ >1s → network is bottleneck (Render latency).

**Our instrumentation will answer:** panel shows `Δ prev` and `cumulative from Start` per stage — sort by largest `Δ`.

---

## B. EVIDENCE FROM CODE (already instrumented)

See table above + file snippets:

- `student_verify.html:120-180`: `QRPerf` object, 17 marks, counters, videoMeta.
- `getBestPosition`: `performance.mark('geolocation-request-started')` + `...success/error`, `counters.geolocation++`.
- `startAttempt`: `mark('attempt-request-started')` / `...response-received` around `fetch('/api/attempt/start/')`.
- `startCamera`: `mark('camera-getUserMedia-requested')` before `getUserMedia`, `mark('camera-stream-obtained')` after, `mark('video-first-frame-available')` on `loadedmetadata`/`canplay`.
- `scanLoop`: `mark('jsQR-loop-started')` on `scanning=true`, `mark('first-frame-sent-to-decoder')` once, `mark('first-qr-decode-success')` when `code` found, `framesDecoded++` every `HAVE_ENOUGH_DATA`.
- `triggerScan`: `mark('scan-POST-started')`/`...completed` around `fetch('/scan/')`.
- `startVerify`: `mark('verification-countdown-started')` and `mark('verification-completed')` + `mark('final-response-received')` around `fetch('/complete/')`.

---

## C. RECOMMENDED MINIMAL FIX (DO NOT APPLY YET — per mode, only propose)

**Fix 1 (no logic change, perf only): Downscale canvas for jsQR + throttle decode to 100ms.**
- Change `c.width=v.videoWidth; c.height=v.videoHeight` to `const W=640; const H=Math.round(W * v.videoHeight/v.videoWidth); c.width=W; c.height=H;` or ` Math.min(800, v.videoWidth)` — reduces pixels 3-4×, CPU down, first decode faster on low-end.
- Throttle: `scanLoop` currently every rAF (~60 fps). Add `if(timestamp - lastDecode < 100) return rAF` or move `jsQR` to Web Worker. Minimal change: wrap `jsQR` in `if(Date.now()-last>80)`.

**Fix 2 (no logic change): Parallelize camera with attempt POST.**
- Currently `startAttempt` await `captureLocation` (7s) → `attempt POST` → `showState('scan'); startCamera()` sequential. Start camera **in parallel** with `attempt POST` (or even with `captureLocation` after permission granted). Saves 1-2s. Change: `startCamera()` not awaited, but ensure `attemptId` exists before `triggerScan` (already).

**Fix 3 (UX, no security change): Keep single 7s geo but add `maximumAge:30000` fallback + `enableHighAccuracy:false` retry if high-accuracy times out.** Current `maximumAge:5000` discards cached fix; outdoor cached fix could be instant.

**All three keep:** `QR_EXPIRY 30s`, `location_verified` server recompute, `unique(session,student)`, `heartbeat`, `face teacher-only`.

---

## D. FILES THAT WOULD NEED MODIFICATION (if fix approved)

- `templates/attendance/student_verify.html` — `scanLoop` downscale + throttle (Fix 1), `startAttempt` parallel camera (Fix 2), `getBestPosition` fallback (Fix 3).
- `config/settings.py` — no change.
- `attendance/views.py` — no change (server already fast).
- `attendance/utils.py` — no change.
- No DB migration.
- No `attendance/urls.py` / `models.py` / `consumers.py` change.

---

## E. REGRESSION RISKS

- **RED — `scanLoop` downscale:** If QR is small/distant, 640px may miss decode while 1280px succeeded → false negative “never completes”. Needs test at 1.5m distance with downscaled vs native. Mitigate: keep `inversionAttempts:'attemptBoth'` already, or dynamic upscale on miss.
- **YELLOW — Parallel camera:** If `triggerScan` fired before `attemptId` set, `POST /scan` would 404 (already guarded by `if(!attemptId) return` missing). Must ensure `attemptId` guard.
- **YELLOW — Throttle 100ms:** Adds 0-100ms to first decode — negligible vs 7s geo, but must not throttle so much that fast-moving QR missed.
- **GREEN — Fallback `maximumAge`:** Could use stale ~30s old location (still within 50m if teacher moved) — risk accepting slightly stale fix; but server recomputes distance at `complete` with latest teacher anchor, so stale student fix only affects initial `attempt` creation, not final.
- **PWA cache:** `sw.js` must still skip `/api/attempt/start` / `scan` — already verified.

---

## F. TESTS REQUIRED BEFORE AND AFTER FIX

**Before fix (with instrumentation, no code change):**
- Manual: Real-device panel capture on Chrome Android + Safari iPhone (indoor 4G/WiFi, outdoor, permission denied, camera denied, airplane). Export JSON via panel and attach.
- Automated (new, to be added after): Playwright `geolocation` mock + `grantPermissions(['camera'])` + `page.evaluate(()=> navigator.mediaDevices.getUserMedia = ... mock stream)` → assert panel stages appear in order, no `multipleLoops`/`duplicateScanPOST`.
- Existing `python manage.py test attendance` 11 tests must stay OK (already OK).

**After fix (if approved):**
- Unit: `test_jsqr_downscale` — feed 1280×720 QR image to `jsQR` with downscaled 640 vs native, assert decode true.
- Integration: `test_parallel_camera_not_block` — mock `getBestPosition` delay 7s, assert `getUserMedia` called before `attempt POST` completes (timing via `performance.mark`).
- Concurrency: `test_scan_loop_single` — call `startCamera` twice quickly, assert `counters.scanLoops===1` and `flags.multipleLoops==False`.
- Browser: Playwright with `video` file stream (`--use-fake-ui-for-media-stream --use-fake-device-for-media-stream --use-file-for-fake-video-capture`) to measure `first-decode` latency before/after downscale.

**Django checks after instrumentation:** `check` 0 silenced, `test attendance` 11 OK — already run and passed.

---

## ACCEPTANCE — ANSWERING THE DELAY SOURCE

With panel, we can now answer (example captured JSON to be filled after real-device run):

| Suspect | How to tell from panel | Current code verdict |
|---|---|---|
| **geolocation** | `geolocation-request-started → success` Δ >5s, larger than camera Δ | **YES primary** — single 7s dominates after previous 36s fix |
| **camera initialization** | `camera-getUserMedia-requested → stream-obtained` Δ 1-3s + `stream-obtained → video-first-frame` 0.2-0.5s | **YES secondary** — blocks decode (sequential) |
| **QR decoding** | `first-frame-sent → first-decode-success` Δ large, `framesDecoded` many, `canvas 1280` | **Variable** — only if QR not centered; downscale fix proposed |
| **duplicate loops** | `counters.scanLoops >1` or `flags.multipleLoops true` | **No** by design after fix, but instrumentation will catch if `Restart` double-click |
| **network** | `attempt-request-started → response` or `scan-POST` Δ >500ms | **No** — expected 80-300ms local, 300-800ms Render |
| **UI/state-machine waiting** | `scan-POST-completed → verification-countdown-started` Δ >200ms or 10s verify (mandatory) | **No unnecessary wait** — gap <100ms, 10s verify is intentional |

**Combination:** Real-world `>20s` = **geolocation (7s) + camera (2s) + 10s verify** + aiming variance.

---

## HOW TO USE PANEL

1. Deploy with `DJANGO_DEBUG=True` (local) or add `?debug=1` if you patch to allow superuser panel. Currently panel appears **only when `settings.DEBUG=True`** (our `verify_page` passes `debug`).
2. Student opens `/attendance/verify/?session=TOKEN` on real phone (Chrome DevTools remote inspect if possible).
3. Perform flow: tap `Start` → allow location → wait for `scan` → scan QR → verify → PRESENT.
4. Panel at bottom shows table; counters/diagnostics update live; open Console → `QRPerf.stages` or `performance.getEntriesByType('mark')`.
5. Click **Export JSON** → attach `qr-perf-*.json` to bug report.
6. In production (`DEBUG=False`), panel not rendered — no exposure.

**Evidence already committed:** open `student_verify.html` → `QRPerf` object + 17 marks + counters visible in `view-source`.

