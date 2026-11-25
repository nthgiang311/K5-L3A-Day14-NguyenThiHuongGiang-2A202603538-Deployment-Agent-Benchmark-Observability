"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis, theo ngày và theo tháng
  • Tổng chi phí vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402
"""
import time

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006


def _keys() -> tuple:
    t = time.gmtime()
    return time.strftime("cost:daily:%Y-%m-%d", t), time.strftime("cost:monthly:%Y-%m", t)


def estimate_tokens(text: str) -> int:
    """Ước lượng ~1.3 token / từ (đủ dùng cho mock LLM)."""
    return max(1, int(len(text.split()) * 1.3))


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys()
    daily, monthly = r.mget(daily_key, monthly_key)
    daily, monthly = float(daily or 0), float(monthly or 0)
    if daily >= settings.daily_budget_usd or monthly >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={"error": "Budget exceeded",
                    "daily_spent_usd": round(daily, 6),
                    "daily_budget_usd": settings.daily_budget_usd,
                    "monthly_spent_usd": round(monthly, 6),
                    "monthly_budget_usd": settings.monthly_budget_usd},
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    daily_key, monthly_key = _keys()
    pipe = r.pipeline()
    pipe.incrbyfloat(daily_key, cost)
    pipe.expire(daily_key, 2 * 24 * 3600)
    pipe.incrbyfloat(monthly_key, cost)
    pipe.expire(monthly_key, 32 * 24 * 3600)
    pipe.execute()
    return cost
