#!/bin/sh
set -e

# Wait for the database to accept connections before migrating.
# DATABASE_URL is parsed only for host/port; default to the compose service.
DB_HOST="${DB_WAIT_HOST:-db}"
DB_PORT="${DB_WAIT_PORT:-3306}"

echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
i=0
until python -c "import socket,sys; s=socket.socket(); s.settimeout(2); s.connect(('${DB_HOST}', ${DB_PORT}))" 2>/dev/null; do
  i=$((i+1))
  if [ "$i" -ge 60 ]; then
    echo "Database not reachable after 60 attempts; giving up." >&2
    exit 1
  fi
  sleep 2
done
echo "Database is up. Running migrations..."

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
