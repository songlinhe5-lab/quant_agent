"""
宏观数据源 DataSourceInterface 适配器 (BE-ARCH-05)

将 FRED / DBnomics / RBI 宏观源适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。

设计原则 (2026-08-07): 仅远程。宏观连接层（FRED REST / DBnomics REST / RBI 爬虫）已下沉
data_subservice（_internal/fred|dbnomics|rbi + 对应 worker）。主服务不再本地调用
fred_service / dbnomics_service / rbi_service，全部经 data_source_router 远程调用。
daemon 对原 macro 服务的直连（BE-ARCH-01 边界）保持不变，本适配器仅服务 Registry.fetch。
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


def _node_of(name: str) -> Any:
    from backend.services.datasource.router import data_source_router

    return data_source_router._nodes.get(name)


class _RemoteMacroDataSource:
    """宏观源远程适配基类：经 data_source_router 调 data_subservice。"""

    source_key: str = ""  # router 节点名（不含 _master）
    name: str = ""
    version: str = "2.0.0"
    capabilities: list[str] = []

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def mode(self) -> str:
        return "remote"

    def is_available(self) -> bool:
        return _node_of(f"{self.source_key}_master") is not None

    async def health(self) -> HealthInfo:
        node = _node_of(f"{self.source_key}_master")
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error=f"{self.source_key}_master 节点未配置",
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
        _action = action.lower()
        if _action not in [c.lower() for c in self.capabilities]:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"{self.name} 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            method = getattr(data_source_router, f"fetch_{self.source_key}")
            resp = await method(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal(f"{self.name.upper()}_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("status") == "success":
            result = Result.make_success(resp.get("data"), source=self.name)
            result.self_recorded = True
            return result

        msg = (resp.get("message") if isinstance(resp, dict) else "") or f"{self.name} fetch failed"
        return Result.make_error(
            ErrorInfo.normal(f"{self.name.upper()}_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


class FREDDataSource(_RemoteMacroDataSource):
    source_key = "fred"
    name = "fred"
    capabilities = ["macro_series", "economic_calendar"]


class DbnomicsDataSource(_RemoteMacroDataSource):
    source_key = "dbnomics"
    name = "dbnomics"
    capabilities = ["economic_calendar"]


class RBIDataSource(_RemoteMacroDataSource):
    source_key = "rbi"
    name = "rbi"
    capabilities = ["economic_calendar"]


def ensure_macro_sources_registered() -> list[str]:
    """幂等注册全部宏观数据源适配器（FRED / DBnomics / RBI）。

    无条件注册——宏观源数据一律经 data_source_router HTTP 代理，不依赖本地服务。
    """
    from backend.services.datasource.source_registry import datasource_registry

    registered: list[str] = []
    for source in (FREDDataSource(), DbnomicsDataSource(), RBIDataSource()):
        if not datasource_registry.has(source.name):
            datasource_registry.register(source)
        registered.append(source.name)
    return registered
