ARG PYTHON_VERSION=3.12

# Inline chapter editor (React + ProseMirror), built into static/chapter-editor/.
FROM node:22-slim AS editor
WORKDIR /build/chapter-editor
COPY chapter-editor/package.json chapter-editor/package-lock.json ./
RUN npm ci
COPY chapter-editor/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# install psycopg2 dependencies.
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /code

WORKDIR /code

COPY requirements.txt /tmp/requirements.txt
RUN set -ex && \
    pip install --upgrade pip && \
    pip install -r /tmp/requirements.txt && \
    rm -rf /root/.cache/
COPY . /code
COPY --from=editor /build/static/chapter-editor /code/static/chapter-editor

# Add entrypoint to run DB migrations / cache table creation on startup
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8080

ENV PORT=8080
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Sync workers give exactly one concurrent request each, and they stay busy for
# the whole response transfer -- chapter renders reach 1.3 MB, so a couple of
# slow clients were enough to fill the listen backlog and make Envoy return
# "upstream connect error ... connection timeout" while the container still
# looked healthy. gthread decouples concurrency from CPU count.
CMD ["sh", "-c", "gunicorn hebrewtool.wsgi:application --bind 0.0.0.0:${PORT} --worker-class gthread --workers 2 --threads 4 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --log-file -"]