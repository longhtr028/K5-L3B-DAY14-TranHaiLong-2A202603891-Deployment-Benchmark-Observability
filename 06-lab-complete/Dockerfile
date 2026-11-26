# ============================================================
# Stage 1: builder — cài dependencies vào /install
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: runtime — image tối giản, non-root, HEALTHCHECK
# ============================================================
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser utils/ ./utils/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health', timeout=3)" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]
