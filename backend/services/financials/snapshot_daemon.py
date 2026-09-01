"""
FIN-09 · 财报当日快照定时刷新 daemon
=====================================

因子 / 回测按 `data_snapshot_id` 整包读 Parquet（docs/19），但宽表只在**回填时**写入——
没回填的日子引用链就断了。本 daemon 每天定点把全部已回填实体的宽表重写进当日快照。

- 挂 `worker.py`（主节点，与 paper_settlement 等同一模式）；
- 触发时刻 `FINANCIALS_SNAPSHOT_HOUR`（默认 6 点，回填低谷期）；
- 刷新失败只告警不退出（daemon 死了明晚就没人刷了）；
- 无实体时直接跳过，不写空快照。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any

import structlog

from backend.core.database import AsyncSessionLocal
from backend.services.financials.service import financials_service

logger = structlog.get_logger(__name__)

SNAPSHOT_HOUR = int(os.getenv("FINANCIALS_SNAPSHOT_HOUR", "6"))


async def refresh_daily_snapshot_now() -> dict[str, Any] | None:
    """立即刷一次当日快照（手动触发 / daemon 共用）。无实体返回 None。"""
    from sqlalchemy import select

    from backend.core.financials_models import FinancialFact

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(FinancialFact.entity_id).distinct())
        if not result.scalars().first():
            logger.info("[FIN-09] 无已回填实体，跳过快照刷新")
            return None
        return await financials_service.refresh_daily_snapshot(session)


async def financials_snapshot_daemon() -> None:
    """每日定点刷新当日财报快照，永不主动退出。"""
    logger.info("财报快照 daemon 启动", hour=SNAPSHOT_HOUR)
    while True:
        now = datetime.now()
        run_at = now.replace(hour=SNAPSHOT_HOUR, minute=0, second=0, microsecond=0)
        if run_at <= now:
            run_at += timedelta(days=1)
        logger.info("下次快照刷新", at=run_at.isoformat())
        await asyncio.sleep((run_at - now).total_seconds())
        try:
            await refresh_daily_snapshot_now()
        except Exception:  # noqa: BLE001  刷新失败只告警，daemon 必须活到明天
            logger.exception("财报当日快照刷新失败")
