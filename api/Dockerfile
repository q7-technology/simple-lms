FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY lms ./lms
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir . && rm -rf /root/.cache

EXPOSE 8000
# behind Caddy, which sets X-Forwarded-For itself: see docker-compose.yml
CMD ["uvicorn", "lms.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
