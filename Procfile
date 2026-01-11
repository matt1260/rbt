release: python manage.py migrate --noinput
web: gunicorn hebrewtool.wsgi --log-file - -e GUNICORN_WORKER=true