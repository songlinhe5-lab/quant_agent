"""
Futu 数据源抽象层 — Protocol + Local 实现

数据源:
- LocalDataSource:  直连 Futu OpenD (通过 ConnectionManager + 各 Handler)

所有数据源本地化采集，Futu OpenD 在同一 VPS 上运行。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class FutuDataSource(Protocol):
    """Futu 数据源统一接口"""

    @property
    def is_available(self) -> bool:
        """当前数据源是否可用"""
        ...

    @property
    def source_type(self) -> str:
        """数据源类型标识: 'local'"""
        ...

    async def fetch(self, action: str, params: dict) -> Optional[Dict[str, Any]]:
        """
        执行数据采集。

        Args:
            action: 操作名 (fetch_quote / fetch_history / ...)
            params: 请求参数 (ticker, ktype, num 等)

        Returns:
            数据 dict，不可用时返回 None
        """
        ...

    def status(self) -> Dict[str, Any]:
        """返回数据源当前状态 (供诊断 API 使用)"""
        ...


# ---------------------------------------------------------------------------
# LocalDataSource — 直连 Futu OpenD
# ---------------------------------------------------------------------------
class LocalDataSource:
    """
    本地直连 Futu OpenD 数据源。

    委托给现有的 ConnectionManager + 各 Handler。
    Futu OpenD 在同一 VPS 上运行，通过 FUTU_HOST:FUTU_PORT 直连。
    """

    def __init__(self, futu_service):
        """
        Args:
            futu_service: FutuService 全局单例
        """
        self._svc = futu_service

    @property
    def is_available(self) -> bool:
        return self._svc.status == "CONNECTED"

    @property
    def source_type(self) -> str:
        return "local"

    async def fetch(
        self,
        action: str,
        params: dict,
        local_handler: Optional[Callable] = None,
        **handler_kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        通过本地 handler 执行数据采集。

        Args:
            action: 操作名
            params: 请求参数
            local_handler: 对应的 handler 方法 (如 quote_handler.get_quote)
            **handler_kwargs: 传给 handler 的关键字参数
        """
        if not self.is_available or local_handler is None:
            return None
        try:
            return await local_handler(**handler_kwargs)
        except Exception as e:
            logger.warning(f"[LocalDataSource] {action} failed: {e}")
            return None

    def status(self) -> Dict[str, Any]:
        conn = self._svc.conn_mgr
        return {
            "type": "local",
            "connected": conn.status == "CONNECTED",
            "host": conn._host,
            "port": conn._port,
            "status": conn.status,
            "error_msg": conn.error_msg,
        }
