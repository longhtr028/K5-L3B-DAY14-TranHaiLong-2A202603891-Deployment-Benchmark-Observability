"""
Cost guard (tiêu chí 8).

Cộng dồn chi phí LLM theo token vào Redis (theo ngày và theo tháng).
Vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
import logging
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent.cost_guard")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_fallback_spend: dict[str, float] = {}


def _daily_key() -> str:
    return f"cost:daily:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"


def _monthly_key() -> str:
    return f"cost:monthly:{datetime.now(timezone.utc).strftime('%Y-%m')}"


def _get_spend(redis_key: str) -> float:
    if r is not None:
        try:
            raw = r.get(redis_key)
            return float(raw) if raw is not None else 0.0
        except redis.RedisError as exc:
            logger.warning("Redis unavailable while reading spend: %s", exc)
    return _fallback_spend.get(redis_key, 0.0)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_spent = _get_spend(_daily_key())
    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Daily budget exceeded "
                f"(${daily_spent:.6f} / ${settings.daily_budget_usd:.6f})"
            ),
        )

    monthly_spent = _get_spend(_monthly_key())
    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Monthly budget exceeded "
                f"(${monthly_spent:.6f} / ${settings.monthly_budget_usd:.6f})"
            ),
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí request vào Redis, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )

    daily_key = _daily_key()
    monthly_key = _monthly_key()

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(daily_key, cost)
            pipe.expire(daily_key, 2 * 24 * 3600)
            pipe.incrbyfloat(monthly_key, cost)
            pipe.expire(monthly_key, 35 * 24 * 3600)
            pipe.execute()
            return cost
        except redis.RedisError as exc:
            logger.warning("Redis unavailable while recording spend: %s", exc)

    _fallback_spend[daily_key] = _fallback_spend.get(daily_key, 0.0) + cost
    _fallback_spend[monthly_key] = _fallback_spend.get(monthly_key, 0.0) + cost
    return cost
