"""
Tushare Remote DataSource Adapter（BE-ARCH-05 注册发现扩展）
=========================================================

将 Tushare 数据源适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用，
并在健康看板 / 链接测试中被统一感知（可挂载 + 可感知）。

设计原则 (2026-08-07): 仅远程。Tushare 连接层已下沉 data_subservice
（_internal/tushare + tushare_worker.py，部署在 CN-DATA 北京节点，DS_CAPABILITIES=tushare）。
主服务不持有 tushare SDK，所有请求经 data_source_router.fetch_tushare() 远程调用，无本地 SDK 兜底。

⚠️ 与 backend/services/tushare/adapter.py 的本地 SDK 模式适配器区分：
- 本地模式依赖主节点安装 tushare 包 + TUSHARE_TOKEN，主节点无 SDK 时不注册；
- 本文件为远程模式适配器，与 akshare 完全对称，无条件注册，使看板始终能感知 tushare 节点
  （即使今日无流量也能展示节点健康度，而非完全隐藏）。
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


class TushareRemoteDataSource:
    """Tushare 远程适配器：经 data_source_router.fetch_tushare() 调用 data_subservice。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "tushare"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> list[str]:
        # 与 router._TS_ACTION_MAP 的 key 对齐（fetch 时统一大写比对）。
        return [
            "STOCK_HISTORY",  # A股日线历史 (pro_bar/daily)
            "STOCK_QUOTE",  # A股实时行情 (rt_k 降级 daily_basic)
            "FUNDAMENTAL",  # 每日指标 / 利润表 / 财务指标
            "FUND_FLOW",  # 沪深港通资金流向 (moneyflow_hsgt)
            "STOCK_LIST",  # 股票列表 (stock_basic)
            "LOWFREQ_HISTORY",  # 周线 / 月线
            "MACRO",  # 宏观经济 (cn_gdp/cn_cpi/cn_ppi/cn_money_supply/cn_shibor)
        ]

    @property
    def mode(self) -> str:
        return "remote"

    def _get_tushare_node(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("tushare_remote")

    def is_available(self) -> bool:
        # 远程模式下，只要 router 里有 tushare_remote 节点即视为可用（无需本地 SDK）。
        return self._get_tushare_node() is not None

    async def health(self) -> HealthInfo:
        node = self._get_tushare_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="tushare_remote 节点未配置（检查 TUSHARE_REMOTE_URL）",
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
                    f"Tushare 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_tushare(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("TUSHARE_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("success"):
            result = Result.make_success(resp.get("data"), source=self.name)
            result.self_recorded = True
            return result

        msg = (resp.get("message") if isinstance(resp, dict) else "") or "tushare fetch failed"
        return Result.make_error(
            ErrorInfo.normal("TUSHARE_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


def ensure_tushare_registered(service: Any = None) -> str:
    """幂等注册 Tushare 远程适配器到 DataSourceRegistry（可挂载 + 可感知看板）。

    无条件注册——Tushare 数据一律经 data_source_router HTTP 代理到 BJ 子服务，
    不依赖本地 SDK。``service`` 参数仅保留向后兼容，已被忽略。
    """
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("tushare"):
        return "tushare"
    datasource_registry.register(TushareRemoteDataSource(), instance_id="default")
    return "tushare"
