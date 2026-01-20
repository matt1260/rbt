#!/usr/bin/env bash
set -euo pipefail

# Optional: disable automatic migrations via env var
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Waiting for database to be ready..."
  for i in $(seq 1 20); do
    # Use showmigrations as a lightweight DB connectivity check
    if python manage.py showmigrations >/dev/null 2>&1; then
      echo "Database reachable."
      break
    fi
    echo "Database not ready, sleeping 3s... ($i)"
    sleep 3
  done

  echo "Running migrations (idempotent)..."
  python manage.py migrate --noinput

  echo "Ensuring cache table exists (idempotent)..."
  python manage.py createcachetable || true

  echo "Collecting static files (if applicable)..."
  python manage.py collectstatic --noinput || true
else
  echo "RUN_MIGRATIONS is set to false; skipping migrations and related startup tasks."
fi

# Exec the container command (e.g. gunicorn) as PID 1, preserving signals
exec "$@"
