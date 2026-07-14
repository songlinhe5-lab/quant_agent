"""
==========================================
Collector Registry - 数据采集器注册表
==========================================
定义所有数据采集器的元数据、后台守护进程工厂和能力声明。
worker.py 通过此注册表按需启动配置的采集器。

BE-ARCH-03: start_collector_daemons 只遍历 factory，零具体服务 import。
新增采集器 = workers/collectors/<name>.py + 本表注册 + COLLECTOR_* env。

环境变量控制:
  COLLECTOR_AKSHARE=true|false
  COLLECTOR_FUTU=true|false
  COLLECTOR_FINNHUB=true|false
  COLLECTOR_YFINANCE=true|false
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from backend.workers.collectors import akshare, finnhub, futu, yfinance

CollectorFactory = Callable[[], Awaitable[Sequence[Coroutine[Any, Any, Any] | Awaitable[Any]]]]


@dataclass
class CollectorDef:
    """采集器定义（元数据 + 启动工厂）"""

    name: str
    env_var: str
    needs_postgres: bool = False
    description: str = ""
    factory: Optional[CollectorFactory] = None


# ==========================================
# 采集器定义表（插件注册点）
# ==========================================
COLLECTORS: Dict[str, CollectorDef] = {
    "akshare": CollectorDef(
        name="akshare",
        env_var="COLLECTOR_AKSHARE",
        needs_postgres=False,
        description="AKShare 港股通/南向资金 (东方财富, 纯请求式无 daemon)",
        factory=akshare.start,
    ),
    "futu": CollectorDef(
        name="futu",
        env_var="COLLECTOR_FUTU",
        needs_postgres=False,
        description="Futu OpenD 港美股行情 (Level 2 盘口 + watchdog)",
        factory=futu.start,
    ),
    "finnhub": CollectorDef(
        name="finnhub",
        env_var="COLLECTOR_FINNHUB",
        needs_postgres=False,
        description="Finnhub 全球内幕交易/新闻 (daemon + API)",
        factory=finnhub.start,
    ),
    "yfinance": CollectorDef(
        name="yfinance",
        env_var="COLLECTOR_YFINANCE",
        needs_postgres=False,
        description="YFinance 宏观指标/大盘数据 (分布式锁 HA daemon)",
        factory=yfinance.start,
    ),
}


def get_enabled_collectors() -> List[str]:
    """根据环境变量返回当前节点启用的采集器列表"""
    enabled = []
    for name, cdef in COLLECTORS.items():
        if os.getenv(cdef.env_var, "false").lower() == "true":
            enabled.append(name)
    return enabled


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
