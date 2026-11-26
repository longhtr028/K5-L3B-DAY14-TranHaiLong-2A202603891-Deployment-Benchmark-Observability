"""
Rate limiting (tiêu chí 7).

Sử dụng sliding window 60 giây lưu bằng Redis sorted set để mọi worker / instance
dùng chung state và giữ nguyên state sau khi restart agent.
"""
import hashlib
import logging
import time
import uuid
from collections import defaultdict

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent.rate_limiter")

WINDOW_SECONDS = 60
_fallback_windows: dict[str, list[float]] = defaultdict(list)


def _key_hash(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def check_rate_limit(key: str) -> None:
    """Kiểm tra sliding window 60s theo API key; vượt giới hạn trả HTTP 429."""
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    redis_key = f"ratelimit:{_key_hash(key)}"

    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.zremrangebyscore(redis_key, 0, window_start)
            pipe.zcard(redis_key)
            _, current_count = pipe.execute()

            if int(current_count) >= limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded ({limit} requests per {WINDOW_SECONDS}s)",
                    headers={"Retry-After": str(WINDOW_SECONDS)},
                )

            member = f"{now}:{uuid.uuid4().hex}"
            pipe = r.pipeline()
            pipe.zadd(redis_key, {member: now})
            pipe.expire(redis_key, WINDOW_SECONDS + 5)
            pipe.execute()
            return
        except HTTPException:
            raise
        except redis.RedisError as exc:
            logger.warning(
                "Redis unavailable for rate limiting, falling back to local window: %s",
                exc,
            )

    # Fallback khi chạy cục bộ không có Redis
    bucket = [ts for ts in _fallback_windows[redis_key] if ts > window_start]
    if len(bucket) >= limit:
        _fallback_windows[redis_key] = bucket
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({limit} requests per {WINDOW_SECONDS}s)",
            headers={"Retry-After": str(WINDOW_SECONDS)},
        )
    bucket.append(now)
    _fallback_windows[redis_key] = bucket
