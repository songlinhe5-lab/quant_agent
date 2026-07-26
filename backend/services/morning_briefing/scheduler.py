"""BRD-01: 盘前早报定时调度器

每日盘前 (默认 09:15 本地时区，可由 env BRIEFING_HOUR / BRIEFING_MINUTE 覆盖)
自动生成全球早报并写入存储，供前端 Dashboard 加载 latest。
生成失败仅告警，不中断守护循环 (API 熔断红线: 绝不死循环耗尽资源)。
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from backend.services.morning_briefing.generator import generate_morning_briefing

logger = logging.getLogger(__name__)


def _seconds_until_next_trigger() -> float:
    """距下次触发的秒数 (默认每天 09:15)"""
    hour = int(os.getenv("BRIEFING_HOUR", "9"))
    minute = int(os.getenv("BRIEFING_MINUTE", "15"))
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def market_briefing_scheduler_daemon() -> None:
    """盘前早报守护循环"""
    logger.info("[Briefing] 盘前早报调度守护启动")
    while True:
        wait = _seconds_until_next_trigger()
        logger.info(f"[Briefing] 下次早报生成将在 {wait:.0f}s 后触发")
        await asyncio.sleep(wait)
        try:
            result = await generate_morning_briefing(market="全球")
            logger.info(f"[Briefing] 定时早报已生成 id={result.id}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Briefing] 定时早报生成失败: {e}")
