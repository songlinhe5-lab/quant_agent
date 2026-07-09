"""
Futu 数据源路由器 — 本地直连 Futu OpenD

所有数据源本地化采集，Futu OpenD 在同一 VPS 上运行。
通过 FUTU_HOST:FUTU_PORT 直连本地 OpenD。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .data_source import LocalDataSource

logger = logging.getLogger(__name__)


class FutuSourceRouter:
    """
    Futu 数据源路由器。

    所有请求走本地直连 OpenD。
    """

    def __init__(self, futu_service):
        """
        Args:
            futu_service: FutuService 全局单例
        """
        self._local = LocalDataSource(futu_service)

    # ── 模式管理 ──────────────────────────────────────────────────

    @property
    def current_mode(self) -> str:
        return "local"

    def switch_mode(self, new_mode: str) -> str:
        """保留接口兼容性，但始终返回 local"""
        logger.info(f"[SourceRouter] 模式切换请求: {new_mode} (当前为单一节点模式，始终 local)")
        return "local"

    # ── 核心路由 ──────────────────────────────────────────────────

    async def route(
        self,
        action: str,
        params: dict,
        local_handler: Optional[Callable] = None,
        **handler_kwargs: Any,
    ) -> Dict[str, Any]:
        """
        路由数据请求到本地 OpenD。

        Args:
            action: 操作名 (fetch_quote / fetch_history / ...)
            params: 请求参数
            local_handler: 本地 handler 方法
            **handler_kwargs: 传给 handler 的关键字参数

        Returns:
            数据 dict 或错误响应
        """
        result = await self._local.fetch(action, params, local_handler=local_handler, **handler_kwargs)
        if result is not None:
            return result
        return self._unavailable()

    # ── 诊断 ──────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """返回路由器状态 (供 /api/v1/futu/source 使用)"""
        return {
            "mode": "local",
            "local": self._local.status(),
        }

    def _unavailable(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Futu 数据源不可用 (本地 OpenD 未连接)"}
