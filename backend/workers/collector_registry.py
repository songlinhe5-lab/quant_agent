"""
==========================================
Collector Registry - 数据采集器注册表
==========================================
定义所有数据采集器的元数据、后台守护进程工厂和能力声明。
worker.py 通过此注册表按需启动配置的采集器。

环境变量控制:
  COLLECTOR_AKSHARE=true|false
  COLLECTOR_FUTU=true|false
  COLLECTOR_FINNHUB=true|false
  COLLECTOR_YFINANCE=true|false
"""

import os
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class CollectorDef:
    """采集器定义"""

    name: str
    env_var: str
    needs_postgres: bool = False
    description: str = ""


# ==========================================
# 采集器定义表
# ==========================================
COLLECTORS: Dict[str, CollectorDef] = {
    "akshare": CollectorDef(
        name="akshare",
        env_var="COLLECTOR_AKSHARE",
        needs_postgres=False,
        description="AKShare 港股通/南向资金 (东方财富, 纯请求式无 daemon)",
    ),
    "futu": CollectorDef(
        name="futu",
        env_var="COLLECTOR_FUTU",
        needs_postgres=False,
        description="Futu OpenD 港美股行情 (Level 2 盘口 + watchdog)",
    ),
    "finnhub": CollectorDef(
        name="finnhub",
        env_var="COLLECTOR_FINNHUB",
        needs_postgres=False,
        description="Finnhub 全球内幕交易/新闻 (daemon + API)",
    ),
    "yfinance": CollectorDef(
        name="yfinance",
        env_var="COLLECTOR_YFINANCE",
        needs_postgres=False,
        description="YFinance 宏观指标/大盘数据 (分布式锁 HA daemon)",
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
    """为启用的采集器启动后台守护进程，返回 asyncio.Task 列表"""
    import asyncio

    from backend.services.yfinance_service import yf_service

    tasks = []

    for name in enabled_collectors:
        if name == "futu":
            # Futu watchdog daemon
            from backend.services.futu.watchdog import get_watchdog
            from backend.services.futu_service import futu_service

            tasks.append(asyncio.create_task(get_watchdog(futu_service).start()))
            print("  [futu] watchdog daemon started")

        elif name == "finnhub":
            # 市场守护进程（新闻/财报/宏观监控，含 Finnhub + AKShare 路由）
            node_type = os.getenv("NODE_TYPE", "master")
            if node_type == "master":
                from backend.services.market_daemon import run_global_daemon

                tasks.append(asyncio.create_task(run_global_daemon()))
                print("  [market-daemon] global daemon started")
            else:
                print("  [finnhub] slave mode: data fetching only, no daemon")

        elif name == "yfinance":
            # YFinance macro data daemon (built-in distributed lock)
            tasks.append(asyncio.create_task(yf_service.macro_data_daemon()))
            print("  [yfinance] macro_data_daemon started")

        elif name == "akshare":
            # AKShare collector daemon (北京 VPS Redis 中继模式)
            from backend.workers.akshare_collector import akshare_collector_daemon

            tasks.append(asyncio.create_task(akshare_collector_daemon()))
            print("  [akshare] collector daemon started (Redis 中继模式)")

    return tasks
