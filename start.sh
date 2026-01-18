#!/bin/sh
set -e

PORT=${PORT:-8000}
WORKERS=${GUNICORN_WORKERS:-2}

if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
  echo "Running migrations..."
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-true}" = "true" ]; then
  echo "Collecting static files..."
  python manage.py collectstatic --noinput
fi

echo "Starting Gunicorn on port ${PORT}..."
exec gunicorn hebrewtool.wsgi --bind ":${PORT}" --workers "${WORKERS}" --log-file -
