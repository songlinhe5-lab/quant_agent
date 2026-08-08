"""
搜索 / 网页抓取数据源 DataSourceInterface 适配器 (BE-ARCH-05)

将独立的搜索与抓取服务 (Tavily / Bocha / Jina Reader) 适配为 DataSourceInterface，
使其可通过 datasource_registry.register() 挂载，并在健康看板 / 链接测试中被统一感知
（可挂载 + 可感知）。

设计原则 (2026-08-07): 外部搜索/抓取经 data_subservice 统一代理（search_worker.py）。
主服务不再直接 httpx 外部 API（api.tavily.com / api.bochaai.com / r.jina.ai），
全部经 data_source_router.fetch_search() → data_subservice 再代理外部调用。
子服务负责实际的 key 管理与 rate limit，主服务仅做 Result 语义化转换。

能力约定（自定义 action，非行情枚举）：
- Tavily / Bocha: capabilities = ["WEB_SEARCH"]
- Jina:           capabilities = ["WEB_SCRAPE"]
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


class _RemoteSearchDataSource:
    """搜索/抓取远程适配基类：经 data_source_router 调 data_subservice 代理。"""

    name: str = ""
    version: str = "2.0.0"
    capabilities: list[str] = []
    provider: str = ""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def mode(self) -> str:
        return "remote"

    def _get_search_node(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("search_master")

    def is_available(self) -> bool:
        return self._get_search_node() is not None

    async def health(self) -> HealthInfo:
        node = self._get_search_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="search_master 节点未配置",
                stats={"capabilities": self.capabilities, "provider": self.provider},
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
                "provider": self.provider,
                "node_url": node.url,
                "node_status": node.status,
                "error_count": node.error_count,
            },
            rate_limit_status=RateLimitStatus(),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal("UNSUPPORTED_ACTION", f"{self.name} 不支持 action: {action}", retryable=False),
                source=self.name,
            )
        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_search(self.name, **params)
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


class TavilyDataSource(_RemoteSearchDataSource):
    """Tavily Search API → DataSourceInterface 薄适配（经 data_subservice 代理）。"""

    name = "tavily"
    capabilities = ["WEB_SEARCH"]
    provider = "api.tavily.com"


class BochaDataSource(_RemoteSearchDataSource):
    """博查 Bocha API → DataSourceInterface 薄适配（经 data_subservice 代理，中文搜索）。"""

    name = "bocha"
    capabilities = ["WEB_SEARCH"]
    provider = "api.bochaai.com"


class JinaDataSource(_RemoteSearchDataSource):
    """Jina Reader API → DataSourceInterface 薄适配（经 data_subservice 代理，网页正文提取）。"""

    name = "jina"
    capabilities = ["WEB_SCRAPE"]
    provider = "r.jina.ai"


def ensure_search_sources_registered() -> list[str]:
    """幂等注册全部搜索/抓取数据源适配器（Tavily / Bocha / Jina）。

    无条件注册——搜索/抓取全部经 data_source_router HTTP 代理子服务，不再直连外部 API。
    """
    from backend.services.datasource.source_registry import datasource_registry

    registered: list[str] = []
    for source in (TavilyDataSource(), BochaDataSource(), JinaDataSource()):
        if not datasource_registry.has(source.name):
            datasource_registry.register(source)
        registered.append(source.name)
    return registered
