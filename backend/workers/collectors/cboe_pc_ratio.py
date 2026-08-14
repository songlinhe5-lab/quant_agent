"""
采集器：CBOE P/C Ratio 周期写入 yf_macro_cache_^CPC

- 由 backend/services/sentiment/sources/cboe_pc_ratio.py 抓取 CBOE 官方每日统计页，
  解析 TOTAL PUT/CALL RATIO，写入 Redis 键 yf_macro_cache_^CPC。
- 写入结构对齐 yf_macro_cache_^VIX（records 形态），使 sentiment_tracker 读侧零改动。
- 常驻后台 daemon，无开关门控（与架构原则一致：源失效在监控显示，恢复即自动补数）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import structlog

from backend.services.sentiment.sources.cboe_pc_ratio import (
    build_cache_records,
    fetch_total_put_call_ratio,
)

logger = structlog.get_logger(__name__)

# 与 yf_macro_cache_^VIX 一致的 TTL（秒）
_CACHE_TTL = 3600
# 刷新间隔（秒）：CBOE 每日收盘后更新一次，15 分钟轮询足够
_REFRESH_INTERVAL = 900
# 启动延迟（秒）：等待网络/依赖就绪
_STARTUP_DELAY = 30


async def _refresh_once() -> None:
    from backend.core.redis_client import redis_client

    pc = await fetch_total_put_call_ratio()
    if pc is None:
        logger.warning("[cboe_pc] 本次未取到 P/C Ratio，跳过写入（不写假数据）")
        return
    records_json = build_cache_records(pc, as_of=datetime.now(timezone.utc))
    await redis_client.set("yf_macro_cache_^CPC", records_json, ex=_CACHE_TTL)
    logger.info("[cboe_pc] 已写入 yf_macro_cache_^CPC", pc_ratio=pc)


async def cboe_pc_daemon() -> None:
    """周期性刷新 P/C Ratio 到 Redis。"""
    print("  [cboe_pc] P/C Ratio daemon started (CBOE daily stats)")
    await asyncio.sleep(_STARTUP_DELAY)
    while True:
        try:
            await _refresh_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[cboe_pc] daemon 循环异常", error=str(exc))
        await asyncio.sleep(_REFRESH_INTERVAL)


async def start() -> list:
    return [cboe_pc_daemon()]
