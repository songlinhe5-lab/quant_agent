"""
Legacy YFinance DataSource Adapter（BE-ARCH-04）

.. deprecated:: v0.1
    后端进程不再本地执行 yfinance（已全量外移到 US-YF-A/B 子服务，
    见 data_subservice/_internal/yfinance）。本适配器仅作为 DataSourceRegistry
    的 “yfinance” 键占位，所有实际取数经 DataSourceRouter 联邦到子服务节点。
    AGENTS §9.4 / BE-ARCH-04 / §10.2。
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
    """Remote-only YFinance 适配器（本地不再跑 yfinance）。

    所有 fetch 委托给 DataSourceRouter，由其选择健康的 US-YF-A/B 子服务节点。
    若构造时显式传入 ``service``（仅测试用），则优先使用传入的 service 执行，
    以便不依赖真实子服务即可完成接口契约测试。
    """

    def __init__(self, service: Any = None) -> None:
        # ``service`` 仅保留用于向后兼容测试；生产路径恒为 None（走子服务）。
        self._service = service
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "yfinance"

    @property
    def version(self) -> str:
        return "1.0.0-remote"

    @property
    def capabilities(self) -> list[str]:
        return ["quote", "history", "info", "macro", "batch_quote", "fetch"]

    @property
    def mode(self) -> str:
        # 后端侧恒为 remote（子服务托管实际流量）
        return os.getenv("DATASOURCE_YFINANCE_MODE", "remote")

    def is_available(self) -> bool:
        # Registry 层面始终可用：fetch 会经 DataSourceRouter 联邦到子服务节点。
        # 本地进程虽不执行 yfinance，但后端对外仍提供 "yfinance" 数据源能力。
        return True

    async def health(self) -> HealthInfo:
        from backend.services.datasource.registry import rate_limit_registry

        throttler = rate_limit_registry.get_throttler(self.name)
        rl = throttler.get_status()
        return HealthInfo(
            healthy=False,  # 本地实例不承载流量
            mode=self.mode,
            connected=False,
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
        """委托给 DataSourceRouter（子服务联邦）。"""
        try:
            if self._service is not None:
                # 测试注入路径：直接调用传入的 service（保持接口契约可测）
                return await self._service.fetch(action, params)
            from backend.services.datasource.router import data_source_router

            return await data_source_router.fetch_yfinance(action, params)
        except Exception as e:  # pragma: no cover - defensive
            err_str = str(e)
            return Result.make_error(
                ErrorInfo.normal("YFINANCE_REMOTE_ERROR", err_str, retryable=True),
                source=self.name,
            )


def ensure_yfinance_registered(service: Optional[Any] = None) -> str:
    """幂等注册 yfinance 远程-only 适配器（占位）。"""
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("yfinance"):
        return "yfinance-default"
    return datasource_registry.register(LegacyYFinanceDataSource(service))
