"""
Futu 数据源路由器 — 根据模式编排 Local / Remote 数据源的切换策略

三种模式 (FUTU_SOURCE_MODE 环境变量):
- local:  强制走本地直连 OpenD (ConnectionManager → FUTU_HOST:FUTU_PORT)
- remote: 强制走远程 slave 代理 (ClusterManager → slave HTTP → slave 本地 OpenD)
- auto:   本地优先，本地不可用时自动降级到 remote (默认，向后兼容)

运行时可通过 switch_mode() 或 HTTP API 热切换。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

from .data_source import LocalDataSource, RemoteDataSource

logger = logging.getLogger(__name__)

VALID_MODES = ("local", "remote", "auto")


class FutuSourceRouter:
    """
    Futu 数据源路由器。

    编排 LocalDataSource 和 RemoteDataSource 的优先级与降级逻辑，
    对外提供统一的 route() 方法。
    """

    def __init__(self, futu_service):
        """
        Args:
            futu_service: FutuService 全局单例
        """
        self._local = LocalDataSource(futu_service)
        self._remote = RemoteDataSource()
        self._mode: str = os.getenv("FUTU_SOURCE_MODE", "auto").lower()
        if self._mode not in VALID_MODES:
            logger.warning(f"[SourceRouter] 无效模式 '{self._mode}'，回退到 auto")
            self._mode = "auto"

    # ── 模式管理 ──────────────────────────────────────────────────

    @property
    def current_mode(self) -> str:
        return self._mode

    def switch_mode(self, new_mode: str) -> str:
        """
        运行时热切换数据源模式。

        Args:
            new_mode: 'local' | 'remote' | 'auto'

        Returns:
            切换后的实际模式
        """
        new_mode = new_mode.lower()
        if new_mode not in VALID_MODES:
            raise ValueError(f"无效模式 '{new_mode}'，可选: {VALID_MODES}")
        old = self._mode
        self._mode = new_mode
        if old != new_mode:
            logger.info(f"[SourceRouter] 数据源模式切换: {old} → {new_mode}")
        return self._mode

    # ── 核心路由 ──────────────────────────────────────────────────

    async def route(
        self,
        action: str,
        params: dict,
        local_handler: Optional[Callable] = None,
        **handler_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        根据当前模式路由数据请求。

        Args:
            action: 操作名 (fetch_quote / fetch_history / ...)
            params: 请求参数
            local_handler: 本地 handler 方法
            **handler_kwargs: 传给 handler 的关键字参数

        Returns:
            数据 dict 或错误响应
        """
        if self._mode == "local":
            return await self._route_local_only(action, params, local_handler, **handler_kwargs)
        elif self._mode == "remote":
            return await self._route_remote_only(action, params)
        else:  # auto
            return await self._route_auto(action, params, local_handler, **handler_kwargs)

    async def _route_local_only(
        self,
        action: str,
        params: dict,
        local_handler: Optional[Callable],
        **handler_kwargs: Any,
    ) -> Dict[str, Any]:
        """强制本地模式"""
        result = await self._local.fetch(action, params, local_handler=local_handler, **handler_kwargs)
        if result is not None:
            return result
        return self._unavailable("local")

    async def _route_remote_only(self, action: str, params: dict) -> Dict[str, Any]:
        """强制远程模式"""
        result = await self._remote.fetch(action, params)
        if result is not None:
            return result
        return self._unavailable("remote")

    async def _route_auto(
        self,
        action: str,
        params: dict,
        local_handler: Optional[Callable],
        **handler_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        auto 模式: 本地优先 → 远程降级。

        优先级: 本地 OpenD → slave-1 → slave-2 → ... → 错误
        行为等同于改造前的 FutuService._route。
        """
        local_available = self._local.is_available
        logger.info(f"[SourceRouter._route_auto] action={action}, local_available={local_available}")

        # 1. 本地可用 → 直接走 handler
        if local_available:
            result = await self._local.fetch(action, params, local_handler=local_handler, **handler_kwargs)
            if result is not None:
                logger.info(f"[SourceRouter._route_auto] local {action} succeeded")
                return result
            logger.warning(f"[SourceRouter._route_auto] local {action} failed, falling back to remote...")

        # 2. 降级到远程 slave
        logger.info(f"[SourceRouter._route_auto] trying remote {action}...")
        result = await self._remote.fetch(action, params)
        logger.info(
            f"[SourceRouter._route_auto] remote {action} returned: is_none={result is None}, type={type(result).__name__ if result else 'None'}"
        )
        if result is not None:
            return result

        # 3. 全链路失败
        logger.warning(f"[SourceRouter._route_auto] ALL FAILED for {action}, returning unavailable")
        return self._unavailable("auto")

    # ── 诊断 ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """返回路由器完整状态 (供 /api/v1/futu/source 使用)"""
        return {
            "mode": self._mode,
            "local": self._local.status(),
            "remote": self._remote.status(),
        }

    def _unavailable(self, mode: str) -> Dict[str, Any]:
        return {"status": "error", "message": f"Futu 数据源不可用 (mode={mode})"}
