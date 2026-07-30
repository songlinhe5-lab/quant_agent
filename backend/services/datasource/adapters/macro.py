"""
宏观数据源 DataSourceInterface 适配器 (BE-ARCH-05)

将独立的宏观服务 (FRED / DBnomics / RBI) 适配为 DataSourceInterface，使其可通过
datasource_registry.register() 挂载，并在健康看板 / 链接测试 / 投票看板中被统一感知
（可挂载 + 可感知）。

依据 docs/14 §10：所有数据源必须实现 DataSourceInterface。采用组合（薄适配）而非改造
原 macro 服务，避免破坏 legacy_market_data 路由与 daemon 对它们的直连（BE-ARCH-01 边界）。
"""

from __future__ import annotations

import os
import time
from typing import Any

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


class FREDDataSource:
    """FREDService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.macro.fred_service import fred_service

            self._service = fred_service
        return self._service

    @property
    def name(self) -> str:
        return "fred"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["macro_series", "economic_calendar"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_FRED_MODE", "internal")

    def is_available(self) -> bool:
        try:
            return bool(self._svc().api_key)
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        api_key = self._svc().api_key
        connected = bool(api_key)
        healthy = connected and not rl.is_throttled
        last_error = None
        if not api_key:
            last_error = "FRED_API_KEY 未配置"
        elif rl.is_throttled:
            last_error = "FRED 处于限流退避期"
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"FRED 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        svc = self._svc()
        if not svc.api_key:
            return Result.make_error(
                ErrorInfo.normal("FRED_NO_KEY", "FRED_API_KEY 未配置", retryable=False),
                source=self.name,
            )

        try:
            if action == "macro_series":
                data = await svc.get_series_observations(
                    series_id=str(params.get("series_id", "")),
                    limit=int(params.get("limit", 100)),
                )
            else:  # economic_calendar
                data = await svc.get_economic_calendar(
                    days_ahead=int(params.get("days_ahead", 7)),
                    days_back=int(params.get("days_back", 0)),
                    skip_cache=bool(params.get("skip_cache", False)),
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FRED_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        msg = (data.get("message") if isinstance(data, dict) else "") or "fred fetch failed"
        return Result.make_error(
            ErrorInfo.normal("FRED_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


class DbnomicsDataSource:
    """DbnomicsService → DataSourceInterface 薄适配（无 Key，仅经济日历子能力）。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.macro.dbnomics import dbnomics_service

            self._service = dbnomics_service
        return self._service

    @property
    def name(self) -> str:
        return "dbnomics"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["economic_calendar"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_DBNOMICS_MODE", "internal")

    def is_available(self) -> bool:
        try:
            self._svc()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        return HealthInfo(
            healthy=not rl.is_throttled,
            mode=self.mode,
            connected=True,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error="DBnomics 处于限流退避期" if rl.is_throttled else None,
            stats={"capabilities": self.capabilities},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"DBnomics 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )
        try:
            data = await self._svc().get_economic_calendar(
                days_ahead=int(params.get("days_ahead", 7)),
                days_back=int(params.get("days_back", 0)),
                skip_cache=bool(params.get("skip_cache", False)),
            )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("DBNOMICS_ERROR", str(e), retryable=True),
                source=self.name,
            )
        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        msg = (data.get("message") if isinstance(data, dict) else "") or "dbnomics fetch failed"
        return Result.make_error(
            ErrorInfo.normal("DBNOMICS_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


class RBIDataSource:
    """RBIService → DataSourceInterface 薄适配（无 Key，仅经济日历子能力）。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.macro.rbi import rbi_service

            self._service = rbi_service
        return self._service

    @property
    def name(self) -> str:
        return "rbi"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return ["economic_calendar"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_RBI_MODE", "internal")

    def is_available(self) -> bool:
        try:
            self._svc()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        rl = _rl_status(self.name)
        return HealthInfo(
            healthy=not rl.is_throttled,
            mode=self.mode,
            connected=True,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error="RBI 处于限流退避期" if rl.is_throttled else None,
            stats={"capabilities": self.capabilities},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"RBI 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )
        try:
            data = await self._svc().get_economic_calendar(
                days_ahead=int(params.get("days_ahead", 7)),
                days_back=int(params.get("days_back", 0)),
                skip_cache=bool(params.get("skip_cache", False)),
            )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("RBI_ERROR", str(e), retryable=True),
                source=self.name,
            )
        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        msg = (data.get("message") if isinstance(data, dict) else "") or "rbi fetch failed"
        return Result.make_error(
            ErrorInfo.normal("RBI_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


def ensure_macro_sources_registered() -> list[str]:
    """幂等注册全部宏观数据源适配器（FRED / DBnomics / RBI）。"""
    from backend.services.datasource.source_registry import datasource_registry

    registered: list[str] = []
    for source in (FREDDataSource(), DbnomicsDataSource(), RBIDataSource()):
        if not datasource_registry.has(source.name):
            datasource_registry.register(source)
        registered.append(source.name)
    return registered
