# syntax=docker/dockerfile:1.7
# Build: docker build -t roommate-billing-agent .
# Run:   see docker-compose.yml / docker-compose.dev.yml

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_PROGRESS_BAR=off \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    WEB_DIR=/app/web

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app alembic.ini pyproject.toml ./
COPY --chown=app:app migrations ./migrations
COPY --chown=app:app web ./web

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=15s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=10).read()"]

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn roommate_billing.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
