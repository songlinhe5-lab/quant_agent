"""BRD-01: 早报 Redis 持久化

设计要点:
- 正常环境写入 Redis (TTL 7 天)，供「分享 URL」与「最新早报」读取。
- 无 Redis 时 (本机单测 / 离线) 自动降级为进程内 dict 兜底，保证引擎可独立运行与测试。
"""

import logging
from typing import Optional

from backend.services.morning_briefing.models import BriefingResult

logger = logging.getLogger(__name__)

# 内存兜底 (Redis 不可用时本地可跑)
_MEMORY: dict[str, BriefingResult] = {}
_MEMORY_LATEST: dict[str, str] = {}  # market -> briefing_id

REDIS_TTL = 7 * 24 * 3600


async def save_briefing(result: BriefingResult) -> None:
    """持久化早报，并记录该市场的最新一份"""
    _MEMORY[result.id] = result
    _MEMORY_LATEST[result.market] = result.id
    try:
        from backend.core.database import get_redis_client

        redis = await get_redis_client()
        await redis.set(f"briefing:{result.id}", result.model_dump_json(), ex=REDIS_TTL)
        await redis.set(
            f"briefing:latest:{result.market}", result.id, ex=REDIS_TTL
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Briefing] Redis 写入失败，使用内存兜底: {e}")


async def get_briefing(briefing_id: str) -> Optional[BriefingResult]:
    if briefing_id in _MEMORY:
        return _MEMORY[briefing_id]
    try:
        from backend.core.database import get_redis_client

        redis = await get_redis_client()
        raw = await redis.get(f"briefing:{briefing_id}")
        if raw:
            return BriefingResult.model_validate_json(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Briefing] Redis 读取失败: {e}")
    return None


async def get_latest_briefing(market: str = "全球") -> Optional[BriefingResult]:
    if market in _MEMORY_LATEST:
        return _MEMORY.get(_MEMORY_LATEST[market])
    try:
        from backend.core.database import get_redis_client

        redis = await get_redis_client()
        bid = await redis.get(f"briefing:latest:{market}")
        if bid:
            return await get_briefing(bid)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Briefing] Redis 读取最新早报失败: {e}")
    return None
