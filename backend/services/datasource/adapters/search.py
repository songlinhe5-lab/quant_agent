"""
搜索 / 网页抓取数据源 DataSourceInterface 适配器 (BE-ARCH-05)

将独立的搜索与抓取服务 (Tavily / Bocha / Jina Reader) 适配为 DataSourceInterface，
使其可通过 datasource_registry.register() 挂载，并在健康看板 / 链接测试中被统一感知
（可挂载 + 可感知）。

依据 docs/14 §10：所有数据源必须实现 DataSourceInterface。采用组合（薄适配）而非改造
原 search_service / WebScrapeTool，避免破坏既有降级链与 Hermes Tool 直连（BE-ARCH-01 边界）。

能力约定（自定义 action，非行情枚举）：
- Tavily / Bocha: capabilities = ["WEB_SEARCH"]，真实各自 endpoint，互不降级污染
- Jina:           capabilities = ["WEB_SCRAPE"]，直接 r.jina.ai 抓取正文
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.services.datasource import (
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)


def _rl_status(name: str) -> RateLimitStatus:
    from backend.services.datasource.registry import rate_limit_registry

    rl = rate_limit_registry.get_throttler(name).get_status()
    return RateLimitStatus(
        is_throttled=rl.is_throttled,
        throttle_until=rl.throttle_until,
        estimated_rpm=rl.estimated_rpm,
        estimated_limit_rpm=rl.estimated_limit_rpm,
        consecutive_rate_limits=rl.consecutive_rate_limits,
        total_rate_limits_1h=rl.total_rate_limits_1h,
        backoff_strategy=rl.backoff_strategy,
    )


class TavilyDataSource:
    """Tavily Search API → DataSourceInterface 薄适配（WEB_SEARCH）。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "tavily"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["WEB_SEARCH"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_TAVILY_MODE", "external_rest")

    def _api_key(self) -> str | None:
        return os.getenv("TAVILY_API_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key())

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        api_key = self._api_key()
        connected = bool(api_key)
        healthy = connected and not rl.is_throttled
        last_error = None
        if not api_key:
            last_error = "TAVILY_API_KEY 未配置"
        elif rl.is_throttled:
            last_error = "Tavily 处于限流退避期"
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities, "provider": "api.tavily.com"},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal("UNSUPPORTED_ACTION", f"Tavily 不支持 action: {action}", retryable=False),
                source=self.name,
            )
        api_key = self._api_key()
        if not api_key:
            return Result.make_error(
                ErrorInfo.normal("TAVILY_NO_KEY", "TAVILY_API_KEY 未配置", retryable=False),
                source=self.name,
            )
        query = str(params.get("query", ""))
        if not query:
            return Result.make_error(
                ErrorInfo.normal("TAVILY_EMPTY_QUERY", "WEB_SEARCH 需要 query 参数", retryable=False),
                source=self.name,
            )
        max_results = int(params.get("max_results", 5))
        payload: dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
        }
        if params.get("include_domains"):
            payload["include_domains"] = params["include_domains"]
        if params.get("exclude_domains"):
            payload["exclude_domains"] = params["exclude_domains"]
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                event_hooks={"request": [httpx_log_request], "response": [httpx_log_response]},
            ) as client:
                resp = await client.post("https://api.tavily.com/search", json=payload)
                resp.raise_for_status()
                results = [
                    {"title": item.get("title"), "href": item.get("url"), "body": item.get("content")}
                    for item in resp.json().get("results", [])
                ]
        except Exception as e:  # noqa: BLE001
            return Result.make_error(ErrorInfo.normal("TAVILY_ERROR", str(e), retryable=True), source=self.name)
        return Result.make_success(results, source=self.name)


class BochaDataSource:
    """博查 Bocha API → DataSourceInterface 薄适配（WEB_SEARCH，中文搜索）。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "bocha"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["WEB_SEARCH"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_BOCHA_MODE", "external_rest")

    def _api_key(self) -> str | None:
        return os.getenv("BOCHA_API_KEY")

    def is_available(self) -> bool:
        return bool(self._api_key())

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        api_key = self._api_key()
        connected = bool(api_key)
        healthy = connected and not rl.is_throttled
        last_error = None
        if not api_key:
            last_error = "BOCHA_API_KEY 未配置"
        elif rl.is_throttled:
            last_error = "Bocha 处于限流退避期"
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities, "provider": "api.bochaai.com"},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal("UNSUPPORTED_ACTION", f"Bocha 不支持 action: {action}", retryable=False),
                source=self.name,
            )
        api_key = self._api_key()
        if not api_key:
            return Result.make_error(
                ErrorInfo.normal("BOCHA_NO_KEY", "BOCHA_API_KEY 未配置", retryable=False),
                source=self.name,
            )
        query = str(params.get("query", ""))
        if not query:
            return Result.make_error(
                ErrorInfo.normal("BOCHA_EMPTY_QUERY", "WEB_SEARCH 需要 query 参数", retryable=False),
                source=self.name,
            )
        max_results = int(params.get("max_results", 5))
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"query": query, "count": max_results}
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                event_hooks={"request": [httpx_log_request], "response": [httpx_log_response]},
            ) as client:
                resp = await client.post("https://api.bochaai.com/v1/web-search", headers=headers, json=payload)
                resp.raise_for_status()
                items = resp.json().get("data", {}).get("webPages", {}).get("value", [])
                results = [
                    {"title": item.get("name"), "href": item.get("url"), "body": item.get("snippet")} for item in items
                ]
        except Exception as e:  # noqa: BLE001
            return Result.make_error(ErrorInfo.normal("BOCHA_ERROR", str(e), retryable=True), source=self.name)
        return Result.make_success(results, source=self.name)


class JinaDataSource:
    """Jina Reader API → DataSourceInterface 薄适配（WEB_SCRAPE，网页正文提取）。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "jina"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["WEB_SCRAPE"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_JINA_MODE", "external_rest")

    def _api_key(self) -> str | None:
        return os.getenv("JINA_API_KEY")

    def is_available(self) -> bool:
        # Jina Reader 公网可用，无 key 亦可降级抓取（仅限流更严），故始终可用
        return True

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        api_key = self._api_key()
        healthy = not rl.is_throttled
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=True,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error="Jina 处于限流退避期" if rl.is_throttled else None,
            stats={
                "capabilities": self.capabilities,
                "provider": "r.jina.ai",
                "api_key_configured": bool(api_key),
            },
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal("UNSUPPORTED_ACTION", f"Jina 不支持 action: {action}", retryable=False),
                source=self.name,
            )
        url = str(params.get("url", ""))
        if not url:
            return Result.make_error(
                ErrorInfo.normal("JINA_EMPTY_URL", "WEB_SCRAPE 需要 url 参数", retryable=False),
                source=self.name,
            )
        if not url.lower().startswith(("http://", "https://")):
            return Result.make_error(
                ErrorInfo.normal("JINA_INVALID_URL", "仅允许 http(s) 协议", retryable=False),
                source=self.name,
            )
        api_key = self._api_key()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                event_hooks={"request": [httpx_log_request], "response": [httpx_log_response]},
            ) as client:
                resp = await client.get(f"https://r.jina.ai/{url}", headers=headers)
                resp.raise_for_status()
                content = resp.text
        except Exception as e:  # noqa: BLE001
            return Result.make_error(ErrorInfo.normal("JINA_ERROR", str(e), retryable=True), source=self.name)
        if len(content) < 50 or "Just a moment" in content:
            return Result.make_error(
                ErrorInfo.normal("JINA_BLOCKED", "Jina 返回内容过短或触发反爬", retryable=True),
                source=self.name,
            )
        return Result.make_success({"url": url, "content": content}, source=self.name)


def ensure_search_sources_registered() -> list[str]:
    """幂等注册全部搜索/抓取数据源适配器（Tavily / Bocha / Jina）。"""
    from backend.services.datasource.source_registry import datasource_registry

    registered: list[str] = []
    for source in (TavilyDataSource(), BochaDataSource(), JinaDataSource()):
        if not datasource_registry.has(source.name):
            datasource_registry.register(source)
        registered.append(source.name)
    return registered
