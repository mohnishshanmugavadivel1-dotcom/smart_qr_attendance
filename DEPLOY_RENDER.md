# 🚀 Deploy Smart QR Attendance to Render (Step-by-Step)

This guide takes you from local folder → live URL `https://smart-qr-attendance.onrender.com` in ~8 minutes.

---

## Method A: One-Click via GitHub (Recommended)

### 1. Push to GitHub
```bash
cd /home/user/smart_qr_attendance
git init
git add .
git commit -m "Smart QR Attendance — Render ready"
# create empty repo on github.com → e.g., https://github.com/<you>/smart-qr-attendance
git branch -M main
git remote add origin https://github.com/<you>/smart-qr-attendance.git
git push -u origin main
```

> If you already have a repo, just `git add . && git commit -m "Render" && git push`.

### 2. Create Render Web Service
1. Go to **https://dashboard.render.com** → **New +** → **Web Service**
2. **Connect** your GitHub repo `smart-qr-attendance`
3. Set:
   - **Name:** `smart-qr-attendance`
   - **Runtime:** `Python 3`
   - **Build Command:** `./build.sh`
   - **Start Command:** `daphne -b 0.0.0.0 -p $PORT config.asgi:application`
   - **Plan:** `Free` (or Starter for always-on)
4. Click **Advanced** → **Add Environment Variable:**

| Key | Value | Notes |
|---|---|---|
| `DJANGO_DEBUG` | `False` |  |
| `DJANGO_SECRET_KEY` | *(Generate — click Generate)* | Render button will create random 50+ chars |
| `PYTHON_VERSION` | `3.13.0` |  |
| `DJANGO_SUPERUSER_USERNAME` | `admin` | optional bootstrap |
| `DJANGO_SUPERUSER_PASSWORD` | `SuperSecure123!` | optional |
| `DJANGO_SUPERUSER_EMAIL` | `you@example.com` | optional |

> **No DB?** Keeps SQLite (`db.sqlite3`) — ok for demo but resets on redeploy. For production add Postgres below.

5. Click **Create Web Service** → watch logs. First build ~2-3 min:
   ```
   pip install ...
   132 static files copied
   Applying migrations
   Seeding demo data … Created teacher01 …
   ```
6. When **Live**, open URL e.g. `https://smart-qr-attendance.onrender.com`

Test:
- `/accounts/login/` → `teacher01 / teacher123` → Create QR → Scan as `student01`

### 3. (Optional) Add Managed Postgres + Redis for Prod
In Render Dashboard → **New +** → **PostgreSQL** → Name `smartqr-db` → Free → Create.
Then back in **Web Service → Environment** → add:

| Key | Value (link) |
|---|---|
| `DATABASE_URL` | **From Database** → `smartqr-db` → `Internal Connection String` |
| `REDIS_URL` | **From Redis** (if you created Redis) → `smartqr-redis` → `Internal Connection String` |

> After adding `DATABASE_URL`, Render auto-redeploys and `build.sh` will run `migrate` against Postgres. InMemoryChannelLayer still works if no Redis, but Redis lets WebSocket work across multiple workers.

---

## Method B: Blueprint (`render.yaml`) — Infrastructure as Code

The repo already contains `render.yaml`:
```yaml
services:
  - type: web
    name: smart-qr-attendance
    env: python
    buildCommand: "./build.sh"
    startCommand: "daphne -b 0.0.0.0 -p $PORT config.asgi:application"
```

1. In Render → **New +** → **Blueprint** → Connect repo → Render detects `render.yaml` → **Apply**
2. Same env vars as above. Approve. Done.

---

## Files Added for Render

| File | Purpose |
|---|---|
| `requirements.txt` (+ whitenoise, dj-database-url, psycopg2-binary, channels_redis, gunicorn) | deps |
| `config/settings.py` (updated) | reads `DATABASE_URL`, `REDIS_URL`, `RENDER_EXTERNAL_HOSTNAME`, `DJANGO_SECRET_KEY`, WhiteNoise, secure cookies |
| `Procfile` | `web: daphne …` fallback |
| `render.yaml` | blueprint |
| `build.sh` | `pip install` → `collectstatic` → `migrate` → `seed_demo` |
| `runtime.txt` | `python-3.13.0` |
| `.env.example` | env template |
| `DEPLOY_RENDER.md` | this file |

---

## Environment Variables Reference

| Var | Required | Example |
|---|---|---|
| `DJANGO_SECRET_KEY` | **Yes (prod)** | `52-char-random` — Generate |
| `DJANGO_DEBUG` | Yes | `False` (prod), `True` (debug) |
| `DATABASE_URL` | No (defaults SQLite) | `postgres://user:pass@host/db` |
| `REDIS_URL` | No (defaults InMemory) | `redis://…` |
| `ALLOWED_HOSTS` | No (auto `RENDER_EXTERNAL_HOSTNAME`) | `.onrender.com` |
| `CSRF_TRUSTED_ORIGINS` | No (auto) | `https://*.onrender.com` |
| `QR_EXPIRY_SECONDS` | No | `30` |

---

## Post-Deploy Checklist

- [ ] Visit `/admin/` → login with superuser or `teacher01`
- [ ] `/classroom/` → create Class & Subject if not seeded
- [ ] Teacher creates QR → student scans → check `PRESENT`
- [ ] `/attendance/teacher/analytics/` → verify charts
- [ ] `/attendance/teacher/history/` → Export CSV
- [ ] Check WebSocket: teacher session page shows `Live via WebSocket` (or `Polling (WS fallback)` if no Redis + single instance is still fine)
- [ ] Set `DJANGO_DEBUG=False` keeps `ALLOWED_HOSTS` locked

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `DisallowedHost` | Add your host to `ALLOWED_HOSTS` or wait — new `config/settings.py` auto-adds `RENDER_EXTERNAL_HOSTNAME` |
| `CSRF verification failed` | Ensure `CSRF_TRUSTED_ORIGINS` includes `https://<your>.onrender.com` — already auto-added |
| `Static files 404` | Check `build.sh` ran `collectstatic`; WhiteNoise serves from `staticfiles/`. No need for S3. |
| `WebSocket 403` | Ensure `AllowedHostsOriginValidator` — already configured; for custom domain add it to `ALLOWED_HOSTS` |
| `DB resets on deploy` | You are on SQLite (ephemeral FS). Create Render Postgres and set `DATABASE_URL` |
| `migrate` fails on Postgres | Check `DATABASE_URL` is **Internal** not External if DB and web in same region |
| Build `psycopg2` error | Already in `requirements.txt`; if still fails set `PYTHON_VERSION=3.13.0` |
| Free instance sleeps | Render Free sleeps after 15 min idle — Upgrade to Starter ($7) for always-on |
| Need logs | Dashboard → Service → Logs → toggle **Show Build + Runtime** |

---

## Local vs Render Behavior

- **Local:** `DJANGO_DEBUG=True`, `DATABASE_URL` empty → SQLite, `InMemoryChannelLayer`, `ALLOWED_HOSTS=*`
- **Render:** `DJANGO_DEBUG=False`, `DATABASE_URL` set → Postgres, `RedisChannelLayer` if `REDIS_URL` set, `ALLOWED_HOSTS` from Render hostname, `WhiteNoise` static, `SECURE_COOKIE` on.

---

## Quick CLI Deploy Check (before push)

```bash
# simulate Render build locally
DJANGO_DEBUG=False DJANGO_SECRET_KEY=testing123 ./build.sh
DJANGO_DEBUG=False DJANGO_SECRET_KEY=testing123 daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

---

## You’re Live 🎉

Share: `https://<your-app>.onrender.com/accounts/register/` for students to self-register as Student/Teacher.

Demo credentials remain (if `seed_demo` kept): `teacher01/teacher123`, `student01/student123`.

Want auto-deploys on `git push`? Render does it by default when connected to GitHub.
