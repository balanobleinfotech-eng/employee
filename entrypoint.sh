#!/bin/sh
set -e

echo "=========================================================="
echo " Starting NETCOM Employee Management Pro Production Server"
echo "=========================================================="

# 1. Database readiness check (with retries if external DB is configured)
if [ -n "$MYSQLHOST" ] || [ -n "$DATABASE_URL" ] || [ -n "$MYSQL_URL" ]; then
    echo "[*] Verifying database connectivity..."
    python -c "
import os, time, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.db import connection
for attempt in range(3):
    try:
        connection.ensure_connection()
        print('    [+] Database connection verified successfully.')
        sys.exit(0)
    except Exception as exc:
        print(f'    [-] Database not ready yet ({attempt + 1}/3): {exc}')
        time.sleep(1)
print('    [!] Database check completed; continuing with available configuration.')
" || true
fi

# 2. Apply database migrations
echo "[*] Running database migrations..."
python manage.py migrate --no-input || echo "[!] Warning: Database migration failed, continuing..."

# 3. Seed initial production data & credentials
echo "[*] Verifying production credentials & seed data..."
python manage.py init_production_data || echo "[!] Warning: Init production data failed, continuing..."

# 4. Ensure static assets are collected
echo "[*] Collecting static assets..."
python manage.py collectstatic --no-input || true

# 5. Resolve Port and launch Gunicorn
PORT=$(echo "$PORT" | tr -d '\r' | tr -d ' ')
PORT="${PORT:-8000}"

if [ -n "$PORT" ] && [ "$PORT" != "8000" ]; then
    echo "[*] Binding Gunicorn web server to 0.0.0.0:${PORT} and 0.0.0.0:8000..."
    exec gunicorn config.wsgi:application \
        --bind "0.0.0.0:${PORT}" \
        --bind "0.0.0.0:8000" \
        --workers 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
else
    echo "[*] Binding Gunicorn web server to 0.0.0.0:${PORT}..."
    exec gunicorn config.wsgi:application \
        --bind "0.0.0.0:${PORT}" \
        --workers 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
