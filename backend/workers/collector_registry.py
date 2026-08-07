"""
==========================================
Collector Registry - 数据采集器注册表
==========================================
定义所有数据采集器的元数据、后台守护进程工厂和能力声明。
worker.py 通过此注册表按需启动配置的采集器。

BE-ARCH-03: start_collector_daemons 只遍历 factory，零具体服务 import。
新增采集器 = workers/collectors/<name>.py + 本表注册。

注意: 采集 daemon 默认全部开启，不再使用 COLLECTOR_* 开关门控。
主服务数据源获取能力默认全开，子服务按 DS_CAPABILITIES 声明响应。
数据源失效统一在监控 (router.get_health_status) 中显示，而非静默禁用 daemon。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.workers.collectors import akshare, finnhub, fmp, yfinance

CollectorFactory = Callable[[], Awaitable[Sequence[Coroutine[Any, Any, Any] | Awaitable[Any]]]]


@dataclass
class CollectorDef:
    """采集器定义（元数据 + 启动工厂）"""

    name: str
    needs_postgres: bool = False
    description: str = ""
    factory: Optional[CollectorFactory] = None


# ==========================================
# 采集器定义表（插件注册点）
# ==========================================
COLLECTORS: Dict[str, CollectorDef] = {
    "akshare": CollectorDef(
        name="akshare",
        needs_postgres=False,
        description="AKShare 港股通/南向资金 (东方财富, 纯请求式无 daemon)",
        factory=akshare.start,
    ),
    "finnhub": CollectorDef(
        name="finnhub",
        needs_postgres=False,
        description="Finnhub 全球内幕交易/新闻 (daemon + API)",
        factory=finnhub.start,
    ),
    "yfinance": CollectorDef(
        name="yfinance",
        needs_postgres=False,
        description="YFinance 宏观指标/大盘数据 (分布式锁 HA daemon)",
        factory=yfinance.start,
    ),
    "fmp": CollectorDef(
        name="fmp",
        needs_postgres=False,
        description="FMP 盘后批量财报缓存 (Redis, credit 预算约束)",
        factory=fmp.start,
    ),
}


def get_enabled_collectors() -> List[str]:
    """返回所有采集器名称（默认全部开启，不再用 COLLECTOR_* 开关门控）。

    采集 daemon 常驻后台，无论数据源当下是否可用都保持开启；
    数据源失效统一在监控 (router.get_health_status) 中显示，而非静默禁用。
    """
    return list(COLLECTORS.keys())


async def start_collector_daemons(
    enabled_collectors: List[str],
) -> list:
    """为启用的采集器启动后台守护进程，返回 asyncio.Task 列表。

    禁止在此函数内 import 具体数据源服务；逻辑全部在 CollectorDef.factory。
    """
    tasks: list = []

    for name in enabled_collectors:
        cdef = COLLECTORS.get(name)
        if cdef is None or cdef.factory is None:
            continue
        coros = await cdef.factory()
        for coro in coros:
            tasks.append(asyncio.create_task(coro))

    return tasks


async def stop_collector_daemons(tasks: Sequence[asyncio.Task]) -> None:
    """取消已启动的采集器 Task（worker 关停路径）。"""
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
