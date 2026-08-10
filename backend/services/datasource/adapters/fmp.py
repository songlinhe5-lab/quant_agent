"""
FMP DataSource Adapter（BE-ARCH-05）

将 FMP 数据源适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。
对齐 docs/14 §10 零侵入扩展规范：业务代码经 Registry.fetch，禁止直连 FMPService。

设计原则 (2026-08-07): 仅远程。FMP 连接层（REST + credit 配额/指标）已下沉
data_subservice（_internal/fmp + fmp_worker.py）。本适配器经 data_source_router
远程调用，不持有本地 FMPService / REST 客户端，无本地 SDK 兜底。

限流说明：credit/限流状态机由 data_subservice 统一处理，本适配器仅做 Result 语义化转换，
限流退避状态以 router 节点健康与 throttler 为准（避免重复计数）。
"""

from __future__ import annotations

import time
from typing import Any, Optional

from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)


class FMPDataSource:
    """FMP 远程适配器：经 data_source_router.fetch_fmp() 调用 data_subservice。"""

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "fmp"

    @property
    def version(self) -> str:
        return "0.2.0"

    @property
    def capabilities(self) -> list[str]:
        # 与子服务 fmp_worker 实际 action + Facade 域方法用的 action 对齐。
        # Facade 用大写 FUNDAMENTAL/INFO，router._FMP_ACTION_MAP 用小写 profile/
        # income_statement/quote 映射为子服务大写 action。此处大小写全声明，
        # 使 datasource_registry.get(source, action) 的 upper 比对均可命中，
        # 避免"按 action 选源"因命名不一致而失效、退化为首个可用实例兜底。
        return [
            "quote",
            "QUOTE",
            "profile",
            "PROFILE",
            "income_statement",
            "INCOME_STATEMENT",
            "credit",
            "CREDIT",
            "FUNDAMENTAL",
            "INFO",
        ]

    @property
    def mode(self) -> str:
        return "remote"

    def _get_fmp_node(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("fmp_master")

    def is_available(self) -> bool:
        return self._get_fmp_node() is not None

    async def health(self) -> HealthInfo:
        node = self._get_fmp_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="fmp_master 节点未配置",
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
                    f"FMP 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_fmp(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FMP_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("status") == "success":
            result = Result.make_success(resp.get("data"), source=self.name)
            result.self_recorded = True  # router 已记录 throttler(on_success)
            return result

        # 错误/降级：router 已记录 throttler，此处仅做语义化转换
        raw_data = resp if isinstance(resp, dict) else {}
        msg = raw_data.get("message") or "fmp fetch failed"
        raw_cat = raw_data.get("error_category")
        is_rl = True
        if raw_cat == ErrorCategory.IP_BLOCKED.value:
            err = ErrorInfo.ip_blocked(message=msg)
        elif raw_cat == ErrorCategory.QUOTA_EXHAUSTED.value:
            err = ErrorInfo.quota_exhausted(message=msg)
        elif any(x in msg for x in ("429", "限流", "Rate limit", "Too Many")):
            err = ErrorInfo.rate_limited(message=msg)
        elif "403" in msg or "IP_BLOCKED" in msg or "权限拒绝" in msg:
            err = ErrorInfo.ip_blocked(message=msg)
        elif "402" in msg or "QUOTA" in msg or "额度" in msg:
            err = ErrorInfo.quota_exhausted(message=msg)
        else:
            err = ErrorInfo.normal("FMP_FETCH_FAILED", msg, retryable=True)
            is_rl = False

        if is_rl:
            result = Result.make_rate_limited(err, source=self.name)
            result.self_recorded = True
        else:
            result = Result.make_error(err, source=self.name)
        return result


def ensure_fmp_registered(service: Optional[Any] = None) -> str:
    """幂等注册 FMP 适配器到 DataSourceRegistry。

    无条件注册——FMP 数据一律经 data_source_router HTTP 代理，
    不依赖本地 FMPService / REST 客户端。
    """
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("fmp"):
        return "fmp-default"
    return datasource_registry.register(FMPDataSource())
