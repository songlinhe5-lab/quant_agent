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

from backend.core.ticker_format import format_yf_ticker
from backend.services.datasource import (
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)

# adapter 标准 action（DataSourceInterface 语义，多为大写） → router fetch_type（小写）。
# router._YF_ACTION_MAP 接受 quote/history/tech/fund_flow/option_chain/financials。
_ACTION_TO_FETCH_TYPE = {
    "QUOTE": "quote",
    "quote": "quote",
    "HISTORY": "history",
    "history": "history",
    "stock_history": "history",
    "TECH": "tech",
    "tech": "tech",
    "technical": "tech",
    "FUND_FLOW": "fund_flow",
    "fund_flow": "fund_flow",
    "OPTION_CHAIN": "option_chain",
    "option_chain": "option_chain",
    "FUNDAMENTAL": "financials",
    "fundamental": "financials",
    "INFO": "financials",
    "info": "financials",
    "FINANCIALS": "financials",
    "financials": "financials",
}


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
        # 必须与 _ACTION_TO_FETCH_TYPE 的键对齐，否则 get(source, action) 的
        # "按 action 选源"比对失效（facade 用大写 QUOTE/HISTORY/FUND_FLOW/
        # OPTION_CHAIN/FUNDAMENTAL/INFO/TECH，router 用小写 fetch_type）。
        # 大小写全声明，确保 upper 比对均可命中。
        return [
            "quote",
            "QUOTE",
            "history",
            "HISTORY",
            "stock_history",
            "tech",
            "TECH",
            "technical",
            "fund_flow",
            "FUND_FLOW",
            "option_chain",
            "OPTION_CHAIN",
            "fundamental",
            "FUNDAMENTAL",
            "info",
            "INFO",
            "financials",
            "FINANCIALS",
            "macro",
            "batch_quote",
            "fetch",
        ]

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
        """委托给 DataSourceRouter（子服务联邦，含多节点逐一备选）。

        adapter 遵循 DataSourceInterface 协议（action 为大写语义、params 含 ticker），
        router.fetch_yfinance 签名为 (ticker, fetch_type, **kwargs)。此处完成参数适配，
        并把 router 返回的 dict 归一为 Result，从而完整复用 router 内
        ``for node in _get_healthy_nodes("yfinance")`` 的多数据源 failover 逻辑。
        """
        try:
            if self._service is not None:
                # 测试注入路径：直接调用传入的 service（保持接口契约可测）
                return await self._service.fetch(action, params)

            # 1) 提取并格式化 ticker（兼容 ticker / symbol 键）
            params = params or {}
            raw_ticker = params.get("ticker") or params.get("symbol") or ""
            if not raw_ticker:
                return Result.make_error(
                    ErrorInfo.normal("YFINANCE_BAD_PARAMS", "yfinance fetch 缺少 ticker/symbol 参数", retryable=False),
                    source=self.name,
                )
            ticker = format_yf_ticker(str(raw_ticker))

            # 2) action → router fetch_type
            fetch_type = _ACTION_TO_FETCH_TYPE.get(action, action.lower())

            # 3) 其余 params 作为 kwargs 透传给 router（剔除已被消费的键）
            kwargs = {k: v for k, v in params.items() if k not in ("ticker", "symbol")}

            from backend.services.datasource.router import data_source_router

            resp = await data_source_router.fetch_yfinance(ticker, fetch_type, **kwargs)

            # 4) dict → Result 归一化（router 内部已做多节点备选）
            if resp.get("success") or resp.get("status") == "success":
                data = resp.get("data") or resp
                return Result.make_success(data, source=self.name)
            return Result.make_error(
                ErrorInfo.normal(
                    "YFINANCE_REMOTE_ERROR",
                    str(resp.get("message", "yfinance 子服务返回失败")),
                    retryable=True,
                ),
                source=self.name,
            )
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
