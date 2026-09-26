#!/usr/bin/env bash
# Render build script — exits on error, shows commands
set -o errexit
set -o xtrace

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Seed demo data (idempotent) — remove if you don't want demo accounts in prod
python manage.py seed_demo || echo "seed_demo skipped"

# Create superuser if DJANGO_SUPERUSER_* vars are set (optional)
# Render can set these as env vars to bootstrap admin
if [[ -n "$DJANGO_SUPERUSER_USERNAME" && -n "$DJANGO_SUPERUSER_PASSWORD" ]]; then
  python manage.py shell << 'PY'
import os
from django.contrib.auth import get_user_model
User=get_user_model()
u=os.environ.get('DJANGO_SUPERUSER_USERNAME')
p=os.environ.get('DJANGO_SUPERUSER_PASSWORD')
e=os.environ.get('DJANGO_SUPERUSER_EMAIL','admin@example.com')
if not User.objects.filter(username=u).exists():
    User.objects.create_superuser(username=u, email=e, password=p, role='teacher')
    print(f"Superuser {u} created")
else:
    print(f"Superuser {u} exists")
PY
fi
