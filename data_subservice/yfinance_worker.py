"""
YFinance Worker — 子服务 yfinance 数据采集适配层
===================================================

封装 YFinanceService 实例的生命周期管理，将 yfinance 核心数据采集能力
(RateLimitedSession、缓存、微批处理、macro_data_daemon) 接入子服务。

子服务直连 Yahoo Finance，不经过路由器 (YF_ROUTER_ENABLED=false)。
DIST-07 将通过 HTTP 端点暴露本 worker 的数据接口。

任务编号: DIST-06
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

from backend.core.logger import logger
from backend.services.yfinance_service import YFinanceService


class YFinanceWorker:
    """
    yfinance 数据采集 worker。

    封装 YFinanceService 实例，管理 macro_data_daemon 后台任务的生命周期，
    并为 DIST-07 HTTP 端点提供数据接口。
    """

    def __init__(self) -> None:
        # 强制关闭路由器模式：子服务直连 Yahoo Finance，不代理到其他节点
        os.environ["YF_ROUTER_ENABLED"] = "false"

        self._service = YFinanceService()
        self._daemon_task: Optional[asyncio.Task] = None
        self._started = False

    # ─────────────────────────────────────────
    #  生命周期
    # ─────────────────────────────────────────

    async def start(self) -> None:
        """启动 macro_data_daemon 后台任务"""
        if self._started:
            logger.warning("[YFinanceWorker] 已启动，跳过重复初始化")
            return

        self._daemon_task = asyncio.create_task(self._service.macro_data_daemon())
        self._started = True
        logger.info("[YFinanceWorker] macro_data_daemon 后台任务已启动")

    async def stop(self) -> None:
        """停止 daemon 任务并释放资源"""
        if self._daemon_task and not self._daemon_task.done():
            self._daemon_task.cancel()
            try:
                await asyncio.wait_for(self._daemon_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            logger.info("[YFinanceWorker] macro_data_daemon 已停止")

        self._service.close()
        self._started = False
        logger.info("[YFinanceWorker] YFinanceService 已关闭，资源已释放")

    # ─────────────────────────────────────────
    #  健康检查
    # ─────────────────────────────────────────

    def get_health(self) -> Dict[str, Any]:
        """返回 yfinance 数据源健康状态 (熔断/限流/正常)"""
        status = self._service.get_health_status()
        status["daemon_running"] = self._daemon_task is not None and not self._daemon_task.done()
        return status

    @property
    def is_daemon_running(self) -> bool:
        """macro_data_daemon 是否正在运行"""
        return self._daemon_task is not None and not self._daemon_task.done()

    # ─────────────────────────────────────────
    #  数据接口 (DIST-07 HTTP 端点将调用这些方法)
    # ─────────────────────────────────────────

    async def fetch(self, ticker: str, fetch_type: str, ttl: int = 3600, **kwargs) -> Dict[str, Any]:
        """
        获取 yfinance 数据 (history / info)。

        返回格式: {"success": bool, "data": Any, "message": str}
        """
        success, data, message = await self._service.fetch_yf_data(ticker, fetch_type, ttl=ttl, **kwargs)
        return {"success": success, "data": data, "message": message}

    async def batched_quote(self, ticker: str, req_type: str = "quote", **kwargs) -> Dict[str, Any]:
        """
        微批处理行情/技术指标请求。

        返回格式: {"status": str, ...}
        """
        return await self._service.get_batched_quote(ticker, req_type=req_type, **kwargs)

    async def tech_indicators(self, ticker: str, **kwargs) -> Dict[str, Any]:
        """
        获取技术指标数据。

        返回格式: {"status": str, "data": {...}}
        """
        return await self._service.get_tech_indicators(ticker, **kwargs)

    async def search(self, query: str) -> Dict[str, Any]:
        """
        搜索 yfinance 标的。

        返回格式: {"status": str, "data": [...]}
        """
        return await self._service.search_tickers(query)

    # ─────────────────────────────────────────
    #  内部属性访问 (供高级用途)
    # ─────────────────────────────────────────

    @property
    def service(self):
        """直接访问底层 YFinanceService 实例"""
        return self._service
