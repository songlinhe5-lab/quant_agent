"""
Futu 数据源抽象层 — Protocol + Local / Remote 实现

两种数据源:
- LocalDataSource:  直连 Futu OpenD (通过 ConnectionManager + 各 Handler)
- RemoteDataSource: 通过 ClusterManager HTTP 代理调用远程 slave 节点

适用场景:
- Master (北京) 直连香港 VPS 的 OpenD  → LocalDataSource (host=HK_VPS_IP)
- Master 通过 ClusterManager 调 slave    → RemoteDataSource
- auto 模式下两者自动切换               → 由 SourceRouter 编排
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
        """数据源类型标识: 'local' | 'remote'"""
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
    当 master 节点通过 FUTU_HOST 指向香港 VPS 的 OpenD 时，
    也属于 "local" 模式（直连 OpenD，不经过 slave HTTP 中转）。
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


# ---------------------------------------------------------------------------
# RemoteDataSource — 通过 ClusterManager 代理
# ---------------------------------------------------------------------------
class RemoteDataSource:
    """
    远程代理数据源。

    通过 ClusterManager.call_collector("futu", ...) 路由至 slave 节点，
    slave 节点再调用其本地的 Futu OpenD。
    """

    def __init__(self):
        self._in_dispatch = False  # 防递归重入

    @property
    def is_available(self) -> bool:
        try:
            from backend.workers.cluster_manager import cluster_manager

            nodes = cluster_manager.get_available_nodes("futu")
            return len(nodes) > 0
        except Exception:
            return False

    @property
    def source_type(self) -> str:
        return "remote"

    async def fetch(self, action: str, params: dict) -> Optional[Dict[str, Any]]:
        """通过 ClusterManager 调用远程 futu 采集器"""
        if self._in_dispatch:
            return None  # 防递归

        self._in_dispatch = True
        try:
            from backend.workers.cluster_manager import cluster_manager

            logger.info(f"[RemoteDataSource] call_collector(futu, {action}, params_keys={list(params.keys())})")
            result = await cluster_manager.call_collector("futu", action, params)
            logger.info(
                f"[RemoteDataSource] call_collector returned: type={type(result).__name__}, keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}"
            )
            if isinstance(result, dict):
                data = result.get("data", result)
                if isinstance(data, dict):
                    # 连接失败类错误 → 返回 None 触发上层降级
                    err_msg = data.get("message", "")
                    if data.get("status") == "error" and (
                        "未连接" in err_msg or "DISCONNECTED" in err_msg or "连接失败" in err_msg
                    ):
                        logger.debug(f"[RemoteDataSource] {action}: connection error on slave")
                        return None
                    # 业务错误（不支持的标的等）→ 原样返回
                    if "status" not in data:
                        data["status"] = "success"
                return data
            logger.warning(f"[RemoteDataSource] {action}: result is not dict, type={type(result)}")
            return None
        except Exception as e:
            logger.warning(f"[RemoteDataSource] {action} failed: {type(e).__name__}: {e}")
            return None
        finally:
            self._in_dispatch = False

    def status(self) -> Dict[str, Any]:
        try:
            from backend.workers.cluster_manager import cluster_manager

            nodes = cluster_manager.get_pool("futu")
            return {
                "type": "remote",
                "available_nodes": len([n for n in nodes if n.is_available]),
                "total_nodes": len(nodes),
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "host": n.host,
                        "status": n.status,
                    }
                    for n in nodes
                ],
            }
        except Exception as e:
            return {"type": "remote", "error": str(e)}
