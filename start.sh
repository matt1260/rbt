#!/bin/bash

# Run migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Start gunicorn
echo "Starting gunicorn..."
exec gunicorn hebrewtool.wsgi --log-file - -e GUNICORN_WORKER=true
