FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    DB_PATH=/app/var/app.db \
    WEB_CONCURRENCY=2

WORKDIR /app

# Dependencies first so this layer is cached between code changes.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend ./backend
COPY frontend ./frontend

# Run as a non-root user; /app/var holds the SQLite registry (mount a volume there).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var && chown -R appuser /app/var
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# Several worker processes per container; each is async and serves many users.
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY} --proxy-headers"]
