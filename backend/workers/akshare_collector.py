"""
AKShare Collector — 北京 VPS 定时采集 daemon
==============================================

方案 A (Redis 中继): 北京 VPS 直连东方财富，定时采集数据写入共享 Redis，
加州主服务 (AKSHARE_MODE=cache) 从 Redis 读取缓存数据。

采集频率:
  - 南向/北向资金: 每 5 分钟 (盘中) / 每 2 小时 (收盘后)
  - 宏观日历: 每 6 小时
  - 经济日历: 每 12 小时

部署:
  北京 VPS 上运行，需确保:
  1. AKSHARE_MODE=direct (默认)
  2. 共享 Redis 可访问 (通过 Tailscale 内网或公网)
  3. COLLECTOR_AKSHARE=true

任务编号: DIST-07 方案 A
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List

from backend.core.logger import logger

# ─────────────────────────────────────────
#  采集任务定义
# ─────────────────────────────────────────

class CollectorTask:
    """采集任务定义"""

    def __init__(self, name: str, interval_trading: int, interval_closed: int, description: str = ""):
        self.name = name
        self.interval_trading = interval_trading  # 盘中采集间隔 (秒)
        self.interval_closed = interval_closed    # 收盘后采集间隔 (秒)
        self.description = description


# 采集任务表
COLLECTOR_TASKS: Dict[str, CollectorTask] = {
    "southbound": CollectorTask(
        name="southbound",
        interval_trading=300,     # 盘中 5 分钟
        interval_closed=7200,     # 收盘后 2 小时
        description="南向资金 (港股通净买入)",
    ),
    "northbound": CollectorTask(
        name="northbound",
        interval_trading=300,
        interval_closed=7200,
        description="北向资金 (外资净买入)",
    ),
    "economic_calendar": CollectorTask(
        name="economic_calendar",
        interval_trading=43200,   # 12 小时
        interval_closed=43200,
        description="宏观经济日历",
    ),
}


def _is_trading_hours() -> bool:
    """
    判断当前是否为港股/A股交易时段 (北京时间 9:15-16:15)。
    简化判断：仅检查小时，不处理节假日。
    """
    from datetime import datetime, timedelta, timezone

    tz_cn = timezone(timedelta(hours=8))
    now = datetime.now(tz_cn)

    # 周末不采集
    if now.weekday() >= 5:
        return False

    hour = now.hour
    minute = now.minute
    # 9:15 - 16:15 (含收盘后半小时缓冲)
    return (hour == 9 and minute >= 15) or (10 <= hour <= 15) or (hour == 16 and minute <= 15)


async def _collect_southbound(service) -> Dict[str, Any]:
    """采集南向资金"""
    result = await service.get_southbound_flow()
    status = result.get("status", "error")
    logger.info(f"[AKShareCollector] 南向资金采集完成: status={status}")
    return result


async def _collect_northbound(service) -> Dict[str, Any]:
    """采集北向资金"""
    result = await service.get_northbound_flow()
    status = result.get("status", "error")
    logger.info(f"[AKShareCollector] 北向资金采集完成: status={status}")
    return result


async def _collect_economic_calendar(service) -> Dict[str, Any]:
    """采集宏观经济日历"""
    result = await service.get_economic_calendar(days_ahead=7, skip_cache=True)
    status = result.get("status", "error")
    logger.info(f"[AKShareCollector] 宏观日历采集完成: status={status}, events={len(result.get('data', []))}")
    return result


# 任务名 → 采集函数映射
_TASK_HANDLERS = {
    "southbound": _collect_southbound,
    "northbound": _collect_northbound,
    "economic_calendar": _collect_economic_calendar,
}


# ─────────────────────────────────────────
#  采集 daemon 主循环
# ─────────────────────────────────────────

async def akshare_collector_daemon(
    enabled_tasks: List[str] | None = None,
) -> None:
    """
    AKShare 采集 daemon 主入口。

    在北京 VPS 上运行，定时采集数据写入共享 Redis。
    加州主服务 (AKSHARE_MODE=cache) 从 Redis 读取。

    Args:
        enabled_tasks: 启用的任务列表，默认全部启用
    """
    # 延迟导入，避免循环依赖
    from backend.services.akshare_service import AKShareService

    if enabled_tasks is None:
        enabled_tasks = list(COLLECTOR_TASKS.keys())

    # 创建 direct 模式的 AKShareService (不依赖环境变量，强制 direct)
    original_mode = os.environ.get("AKSHARE_MODE", "")
    os.environ["AKSHARE_MODE"] = "direct"

    service = AKShareService()
    # 恢复原环境变量
    if original_mode:
        os.environ["AKSHARE_MODE"] = original_mode

    logger.info(f"[AKShareCollector] 启动采集 daemon, 任务列表: {enabled_tasks}")

    # 记录每个任务的最后采集时间
    last_collected: Dict[str, float] = {name: 0.0 for name in enabled_tasks}

    while True:
        try:
            is_trading = _is_trading_hours()
            now = time.time()

            for task_name in enabled_tasks:
                task_def = COLLECTOR_TASKS.get(task_name)
                handler = _TASK_HANDLERS.get(task_name)
                if not task_def or not handler:
                    logger.warning(f"[AKShareCollector] 未知任务: {task_name}")
                    continue

                # 根据交易时段选择采集间隔
                interval = task_def.interval_trading if is_trading else task_def.interval_closed

                # 检查是否到了采集时间
                elapsed = now - last_collected[task_name]
                if elapsed < interval:
                    continue

                try:
                    await handler(service)
                    last_collected[task_name] = time.time()
                except Exception as e:
                    logger.error(f"[AKShareCollector] {task_name} 采集异常: {e}")
                    # 失败后 60 秒重试
                    last_collected[task_name] = now - interval + 60

            # 休眠 30 秒后重新检查
            await asyncio.sleep(30)

        except asyncio.CancelledError:
            logger.info("[AKShareCollector] 采集 daemon 已取消")
            break
        except Exception as e:
            logger.error(f"[AKShareCollector] daemon 主循环异常: {e}")
            await asyncio.sleep(60)
