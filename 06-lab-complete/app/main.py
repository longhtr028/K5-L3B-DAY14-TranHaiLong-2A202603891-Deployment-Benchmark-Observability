"""
Production AI Agent — Part 6 Final Project.

Đáp ứng đầy đủ 12 tiêu chí production readiness:
- Health (/health) & Readiness (/ready)
- API Key authentication (X-API-Key)
- Sliding-window rate limiting trên Redis
- Token-based cost guard trên Redis
- 12-Factor config từ environment variables
- Structured JSON logging
- Graceful shutdown khi nhận SIGTERM
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import signal
import sys
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mọi dòng log của ứng dụng thành một JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
            "env": settings.environment,
        }
        extra_fields = getattr(record, "extra_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> logging.Logger:
    app_logger = logging.getLogger("agent")
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    app_logger.setLevel(level)
    app_logger.propagate = False
    if not app_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        app_logger.addHandler(handler)
    return app_logger


logger = _configure_logging()


def _log(level: int, event: str, message: str, **fields) -> None:
    logger.log(level, message, extra={"event": event, "extra_fields": fields})


@asynccontextmanager
async def lifespan(_app: FastAPI):
    previous_sigterm = signal.getsignal(signal.SIGTERM)

    def _on_sigterm(signum, frame):
        _log(logging.INFO, "sigterm", "Received SIGTERM, starting graceful shutdown")
        if callable(previous_sigterm):
            previous_sigterm(signum, frame)

    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        pass

    _log(
        logging.INFO,
        "startup",
        "Production AI Agent started",
        port=settings.port,
        rate_limit_per_minute=settings.rate_limit_per_minute,
        daily_budget_usd=settings.daily_budget_usd,
    )
    try:
        yield
    finally:
        close_redis()
        _log(logging.INFO, "shutdown", "Graceful shutdown complete")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        _log(
            logging.ERROR,
            "unhandled_error",
            "Unhandled exception during request",
            method=request.method,
            path=request.url.path,
            status=500,
            ms=elapsed_ms,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    _log(
        logging.INFO,
        "request",
        f"{request.method} {request.url.path} -> {response.status_code}",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=elapsed_ms,
    )
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default="anonymous", max_length=128)


@app.get("/health")
def health():
    """Liveness probe: luôn trả 200 khi process còn sống, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness probe: trả 200 khi Redis sẵn sàng, 503 khi mất kết nối Redis."""
    if not redis_healthy():
        _log(logging.WARNING, "readiness_failed", "Redis health check failed")
        raise HTTPException(status_code=503, detail="Service not ready: Redis unavailable")
    return {"status": "ready", "redis": "connected"}


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4 + 1)


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()

    answer = llm_ask(body.question)
    input_tokens = _estimate_tokens(body.question)
    output_tokens = _estimate_tokens(answer)
    cost_usd = record_cost(input_tokens, output_tokens)

    _log(
        logging.INFO,
        "ask_completed",
        "Processed /ask request",
        user_id=body.user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost_usd, 8),
    )
    return {
        "question": body.question,
        "answer": answer,
        "user_id": body.user_id,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost_usd, 8),
        },
    }
