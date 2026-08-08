"""
AKShare DataSource Adapter（BE-ARCH-05 注册发现扩展）
====================================================

将 AKShare 数据源适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。

设计原则 (2026-08-07): 仅远程。AKShare 连接层已下沉 data_subservice（_internal/akshare +
akshare_worker.py，部署在 CN-AKSHARE 北京节点）。主服务不持有 akshare SDK，所有请求经
data_source_router.fetch_akshare() 远程调用，无本地 SDK 兜底。
"""

from __future__ import annotations

import time
from typing import Any

from backend.services.datasource import (
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)


class AKShareDataSource:
    """AKShare 远程适配器：经 data_source_router.fetch_akshare() 调用 data_subservice。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "akshare"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> list[str]:
        return [
            "FUND_FLOW",
            "ECONOMIC_CALENDAR",
        ]

    @property
    def mode(self) -> str:
        return "remote"

    def _get_akshare_node(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("akshare_remote")

    def is_available(self) -> bool:
        return self._get_akshare_node() is not None

    async def health(self) -> HealthInfo:
        node = self._get_akshare_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="akshare_remote 节点未配置",
                stats={"capabilities": self.capabilities},
                rate_limit_status=RateLimitStatus(),
            )
        connected = node.status == "healthy"
        return HealthInfo(
            healthy=connected,
            mode="remote",
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=f"error_count={node.error_count}" if node.error_count else None,
            stats={
                "capabilities": self.capabilities,
                "node_url": node.url,
                "node_status": node.status,
                "error_count": node.error_count,
            },
            rate_limit_status=RateLimitStatus(),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        _action = action.upper()
        if _action not in [c.upper() for c in self.capabilities]:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"AKShare 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_akshare(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("AKSHARE_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("status") == "success":
            result = Result.make_success(resp.get("data"), source=self.name)
            result.self_recorded = True
            return result

        msg = (resp.get("message") if isinstance(resp, dict) else "") or "akshare fetch failed"
        return Result.make_error(
            ErrorInfo.normal("AKSHARE_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


def ensure_akshare_registered(service: Any = None) -> str:
    """幂等注册 AKShare 适配器到 DataSourceRegistry（可挂载）。

    无条件注册——AKShare 数据一律经 data_source_router HTTP 代理，不依赖本地 SDK。
    ``service`` 参数仅保留向后兼容，已被忽略。
    """
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("akshare"):
        return "akshare"
    datasource_registry.register(AKShareDataSource(), instance_id="default")
    return "akshare"
