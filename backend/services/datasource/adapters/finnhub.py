"""
Finnhub DataSource Adapter（BE-ARCH-05）

将现有 FinnhubService 适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。
对齐 docs/14 §10 零侵入扩展规范：业务代码经 Registry.fetch，禁止直连 FinnhubService。

限流说明：FinnhubService 各方法内部已接入 rate_limit_registry（SVC-08），
在 429/403 → on_rate_limit、成功 → on_success。本适配器返回 Result 时仅做语义化
转换，限流退避的真实状态以 throttler 为准（避免重复计数）。
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
    ResultStatus,
)


class FinnhubDataSource:
    """FinnhubService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.finnhub_service import finnhub_service

            self._service = finnhub_service
        return self._service

    @property
    def name(self) -> str:
        return "finnhub"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return [
            "earnings",
            "company_news",
            "market_news",
            "economic_calendar",
            "insider_trading",
            "stock_history",
        ]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_FINNHUB_MODE", "internal")

    def is_available(self) -> bool:
        # 模块可加载即视为可用；缺 API Key 由 fetch 返回不可重试错误
        try:
            self._svc()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        from backend.services.datasource.registry import rate_limit_registry

        throttler = rate_limit_registry.get_throttler(self.name)
        rl = throttler.get_status()
        api_key = self._svc()._get_api_key()
        healthy = bool(api_key) and not rl.is_throttled
        last_error = None
        if not api_key:
            last_error = "FINNHUB_API_KEY 未配置"
        elif rl.is_throttled:
            last_error = "Finnhub 处于限流退避期"
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=bool(api_key),
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities},
            rate_limit_status=RateLimitStatus(
                is_throttled=rl.is_throttled,
                throttle_until=rl.throttle_until,
                estimated_rpm=rl.estimated_rpm,
                estimated_limit_rpm=rl.estimated_limit_rpm,
                consecutive_rate_limits=rl.consecutive_rate_limits,
                total_rate_limits_1h=rl.total_rate_limits_1h,
                backoff_strategy=rl.backoff_strategy,
            ),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"Finnhub 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        svc = self._svc()
        # 缺 Key 快速失败（不可重试）
        if not svc._get_api_key():
            return Result.make_error(
                ErrorInfo.normal("FINNHUB_NO_KEY", "FINNHUB_API_KEY 未配置", retryable=False),
                source=self.name,
            )

        try:
            if action == "earnings":
                data = await svc.get_earnings_calendar(
                    days_ahead=int(params.get("days_ahead", 7)),
                    days_back=int(params.get("days_back", 0)),
                    skip_cache=bool(params.get("skip_cache", False)),
                )
            elif action == "company_news":
                data = await svc.get_company_news(
                    ticker=str(params.get("ticker", "")),
                    days_back=int(params.get("days_back", 3)),
                    skip_cache=bool(params.get("skip_cache", False)),
                )
            elif action == "market_news":
                data = await svc.get_market_news(category=str(params.get("category", "general")))
            elif action == "economic_calendar":
                data = await svc.get_economic_calendar(
                    days_ahead=int(params.get("days_ahead", 7)),
                    days_back=int(params.get("days_back", 0)),
                    skip_cache=bool(params.get("skip_cache", False)),
                )
            elif action == "insider_trading":
                data = await svc.get_insider_transactions(
                    ticker=str(params.get("ticker", "")),
                    limit=int(params.get("limit", 30)),
                )
            elif action == "stock_history":
                data = await svc.get_stock_history(
                    ticker=str(params.get("ticker", "")),
                    days_back=int(params.get("days_back", 365)),
                )
            else:  # pragma: no cover - 已被 capabilities 前置拦截
                return Result.make_error(
                    ErrorInfo.normal(
                        "UNSUPPORTED_ACTION",
                        f"Finnhub 不支持 action: {action}",
                        retryable=False,
                    ),
                    source=self.name,
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FINNHUB_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        if isinstance(data, dict) and data.get("status") in ("skipped", "unavailable"):
            return Result.make_error(
                ErrorInfo.normal(
                    "FINNHUB_UNAVAILABLE",
                    data.get("message", "Finnhub 暂不可用"),
                    retryable=False,
                ),
                source=self.name,
            )

        # 错误/降级：检查是否限流类（FinnhubService 内部已记录 throttler，此处仅语义化）
        msg = (data.get("message") if isinstance(data, dict) else "") or "finnhub fetch failed"
        if any(x in msg for x in ("429", "限流", "Rate limit", "Too Many", "403")):
            return Result.make_rate_limited(
                ErrorInfo.rate_limited(code="FINNHUB_RATE_LIMIT", message=msg),
                source=self.name,
            )
        return Result.make_error(
            ErrorInfo.normal("FINNHUB_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


def ensure_finnhub_registered(service: Optional[Any] = None) -> str:
    """幂等注册 Finnhub 适配器。"""
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("finnhub"):
        return "finnhub-default"
    return datasource_registry.register(FinnhubDataSource(service))
