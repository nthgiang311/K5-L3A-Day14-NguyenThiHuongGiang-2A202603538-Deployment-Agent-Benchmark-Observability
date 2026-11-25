"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 + header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung, còn sau restart
"""
import hashlib
import time
import uuid

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key dạng rõ trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:24]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()

    pipe = r.pipeline()
    pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
    pipe.zcard(bucket)
    _, count = pipe.execute()

    if count >= limit:
        oldest = r.zrange(bucket, 0, 0, withscores=True)
        retry_after = int(oldest[0][1] + WINDOW_SECONDS - now) + 1 if oldest else WINDOW_SECONDS
        retry_after = max(retry_after, 1)
        raise HTTPException(
            status_code=429,
            detail={"error": "Rate limit exceeded", "limit": limit,
                    "window_seconds": WINDOW_SECONDS, "retry_after_seconds": retry_after},
            headers={"Retry-After": str(retry_after),
                     "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
        )

    pipe = r.pipeline()
    pipe.zadd(bucket, {f"{now}-{uuid.uuid4().hex[:8]}": now})
    pipe.expire(bucket, WINDOW_SECONDS + 5)
    pipe.execute()
