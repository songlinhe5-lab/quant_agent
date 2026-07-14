"""
Legacy YFinance DataSource Adapter（BE-ARCH-04）

将现有 YFinanceService 适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from backend.services.datasource import (
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)


class LegacyYFinanceDataSource:
    """YFinanceService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.yfinance_service import yf_service

            self._service = yf_service
        return self._service

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def version(self) -> str:
        return "1.0.0-legacy"

    @property
    def capabilities(self) -> list[str]:
        return ["quote", "history", "info", "macro", "batch_quote", "fetch"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_YFINANCE_MODE", "internal")

    def is_available(self) -> bool:
        return True

    async def health(self) -> HealthInfo:
        from backend.services.datasource.registry import rate_limit_registry

        throttler = rate_limit_registry.get_throttler(self.name)
        rl = throttler.get_status()
        return HealthInfo(
            healthy=True,
            mode=self.mode,
            connected=True,
            uptime_seconds=time.monotonic() - self._started_at,
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
        ticker = str(params.get("ticker", "") or "")
        fetch_type = str(
            params.get("fetch_type")
            or (action if action in ("history", "info", "quote") else "history")
        )
        passthrough = {
            k: v
            for k, v in params.items()
            if k not in ("ticker", "fetch_type", "action")
        }
        try:
            success, data, msg = await self._svc().fetch_yf_data(
                ticker, fetch_type, **passthrough
            )
        except Exception as e:
            err_str = str(e)
            if any(
                x in err_str
                for x in ("429", "Rate limit", "Too Many Requests", "YFRateLimitError")
            ):
                return Result.make_rate_limited(
                    ErrorInfo.rate_limited(message=err_str),
                    source=self.name,
                )
            return Result.make_error(
                ErrorInfo.normal("YFINANCE_ERROR", err_str, retryable=True),
                source=self.name,
            )

        if success:
            return Result.make_success(data, source=self.name)
        if msg and any(
            x in msg for x in ("限流", "429", "冷却", "熔断", "Rate limit")
        ):
            return Result.make_rate_limited(
                ErrorInfo.rate_limited(message=msg or "yfinance rate limited"),
                source=self.name,
            )
        return Result.make_error(
            ErrorInfo.normal("YFINANCE_FETCH_FAILED", msg or "fetch failed", retryable=True),
            source=self.name,
        )


def ensure_yfinance_registered(service: Optional[Any] = None) -> str:
    """幂等注册 yfinance Legacy 适配器。"""
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("yfinance"):
        return "yfinance-default"
    return datasource_registry.register(LegacyYFinanceDataSource(service))
