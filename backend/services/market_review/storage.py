"""
MRKT-01: 市场复盘 Redis 存储层

键空间约定:
- quant:market_review:{market}:{date}  → 单日复盘 JSON (TTL 30天)
- quant:market_review:index:{market}   → 最近 N 天日期列表 (Sorted Set, score=日期戳)
"""

from __future__ import annotations

from typing import Optional

from backend.core.redis_client import redis_client
from backend.services.market_review.models import MarketDailyReview, MarketType

# 复盘数据保留 30 天
_REVIEW_TTL_DAYS = 30
_REVIEW_TTL_SECONDS = _REVIEW_TTL_DAYS * 86400

# 索引键前缀
_INDEX_PREFIX = "quant:market_review:index"


async def save_market_review(review: MarketDailyReview) -> str:
    """持久化一份市场复盘报告到 Redis。

    Returns:
        存储的 Redis key
    """
    key = review.redis_key()
    payload = review.model_dump_json()

    # 写入主数据 (TTL 30天)
    await redis_client.set(key, payload, ex=_REVIEW_TTL_SECONDS)

    # 更新日期索引 (Sorted Set, score = YYYYMMDD 整数)
    index_key = f"{_INDEX_PREFIX}:{review.market.value}"
    date_score = int(review.date.replace("-", ""))
    await redis_client.zadd(index_key, {review.date: date_score})
    # 裁剪索引只保留最近 30 条
    await redis_client.zremrangebyrank(index_key, 0, -(_REVIEW_TTL_DAYS + 1))

    return key


async def get_market_review(date: str, market: MarketType) -> Optional[MarketDailyReview]:
    """查询指定日期+市场的复盘报告。

    Args:
        date: YYYY-MM-DD
        market: 市场类型
    """
    key = f"quant:market_review:{market.value}:{date}"
    raw = await redis_client.get(key)
    if not raw:
        return None
    return MarketDailyReview.model_validate_json(raw)


async def get_recent_reviews(market: MarketType, days: int = 3) -> list[MarketDailyReview]:
    """获取最近 N 天的复盘报告（按日期降序）。

    用于个股分析时的判因上下文注入。
    """
    index_key = f"{_INDEX_PREFIX}:{market.value}"
    # 取最近 N 个日期 (降序)
    dates = await redis_client.zrevrange(index_key, 0, days - 1)
    if not dates:
        return []

    reviews = []
    for d in dates:
        review = await get_market_review(d, market)
        if review:
            reviews.append(review)
    return reviews


async def get_latest_review(market: MarketType) -> Optional[MarketDailyReview]:
    """获取指定市场最新一份复盘报告。"""
    results = await get_recent_reviews(market, days=1)
    return results[0] if results else None


async def list_available_dates(market: MarketType, limit: int = 30) -> list[str]:
    """列出指定市场可用的复盘日期（降序）。"""
    index_key = f"{_INDEX_PREFIX}:{market.value}"
    dates = await redis_client.zrevrange(index_key, 0, limit - 1)
    return list(dates) if dates else []


async def delete_market_review(date: str, market: MarketType) -> bool:
    """删除指定复盘（管理用途）。"""
    key = f"quant:market_review:{market.value}:{date}"
    deleted = await redis_client.delete(key)
    index_key = f"{_INDEX_PREFIX}:{market.value}"
    await redis_client.zrem(index_key, date)
    return deleted > 0
