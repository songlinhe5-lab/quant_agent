"""
Futu DataSource Adapter（BE-ARCH-05 / BE-ARCH-07）
=================================================

将 data_subservice（Futu OpenD 宿主）的 HTTP 接口适配为 DataSourceInterface，
使 Facade 经 DataSourceRegistry 统一调度 futu 数据。

数据流（唯一路径）：
  FutuDataSource.fetch() → data_source_router.fetch_futu() → HTTP → data_subservice
  data_source_router 内部负责 action 映射、HMAC 签名、节点健康感知。
  设计原则 (2026-08-07): 仅远程，无本地 SDK 降级通道。

节点约束：Futu OpenD 仅部署在 US-MASTER 主节点，由 data_subservice (DS_CAPABILITIES=futu)
持有长连接。主服务不持有 SDK，所有 futu 访问经 HTTP 代理。

状态感知：
  - is_available() → 查询 router 中 futu_master 节点健康状态
  - health()      → 返回远程节点诊断信息（URL / status / error_count）
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


class FutuDataSource:
    """Futu → DataSourceInterface 适配。

    所有数据请求经 data_source_router.fetch_futu()（HTTP → data_subservice），
    不直连本地 futu_service。仅远程，无本地 SDK 降级。
    """

    def __init__(self) -> None:
        self._started_at = time.monotonic()

    @property
    def name(self) -> str:
        return "futu"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def capabilities(self) -> list[str]:
        # 必须与实际子服务能力对齐（data_subservice/futu_worker.py + _FUTU_ACTION_MAP）。
        # Facade 域方法所用的 action（WARRANT_CHAIN/SCREEN_STOCKS）必须在此声明，
        # 否则 datasource_registry.get(source, action) 的"按 action 选源"语义失效。
        return [
            "QUOTE",
            "HISTORY",
            "FUND_FLOW",
            "OPTION_CHAIN",
            "FUNDAMENTAL",
            "ORDER_BOOK",
            "WARRANT_CHAIN",
            "SNAPSHOT",
            "STOCK_BASICINFO",
            "ACCOUNT_INFO",
            "SCREEN_STOCKS",
        ]

    # ── 远程节点状态感知 ──────────────────────────────────────

    def _get_futu_node(self) -> Any:
        """取 router 中 futu_master 节点引用（不存在返回 None）。"""
        from backend.services.datasource.router import data_source_router

        return data_source_router._nodes.get("futu_master")

    def is_available(self) -> bool:
        """远程 futu_master 节点是否可达。

        只要 router 初始化完成（futu_master 节点存在）即视为可调用——
        节点健康度由 router 内部熔断/降级机制处理，不在 adapter 层拦截。
        """
        return self._get_futu_node() is not None

    async def health(self) -> HealthInfo:
        """返回 futu_master 远程节点诊断信息。"""
        node = self._get_futu_node()
        if node is None:
            return HealthInfo(
                healthy=False,
                mode="remote",
                connected=False,
                uptime_seconds=time.monotonic() - self._started_at,
                last_error="futu_master 节点未配置",
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

    # ── 数据获取（唯一入口） ──────────────────────────────────

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        _action = action.upper()
        if _action not in [c.upper() for c in self.capabilities]:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"Futu 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        from backend.services.datasource.router import data_source_router

        try:
            resp = await data_source_router.fetch_futu(_action, **params)
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FUTU_ROUTER_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(resp, dict) and resp.get("status") == "success":
            payload = resp.get("data")
            # 解包子服务内部信封: {"status":"success","data":<真实业务数据>}
            # _normalize_response 不会剥离该层, 导致 payload 仍是 dict 信封,
            # 上层 (如 calculate_technical_indicators / get_history) 拿到 dict 而非 list 而崩溃。
            if isinstance(payload, dict) and payload.get("status") == "success" and "data" in payload:
                payload = payload["data"]
            return Result.make_success(payload, source=self.name)

        msg = (resp.get("message") if isinstance(resp, dict) else "") or "futu fetch failed"
        # 期权链偶发失败不熔断（其它能力照常）
        option_chain_non_retryable = _action == "OPTION_CHAIN"
        if any(x in msg for x in ("429", "限流", "Rate limit", "Too Many", "403")):
            return Result.make_rate_limited(
                ErrorInfo.rate_limited(code="FUTU_RATE_LIMIT", message=msg),
                source=self.name,
            )
        return Result.make_error(
            ErrorInfo.normal("FUTU_FETCH_FAILED", msg, retryable=not option_chain_non_retryable),
            source=self.name,
        )


def ensure_futu_registered() -> str:
    """幂等注册 Futu 适配器到 DataSourceRegistry。

    无条件注册——Futu 数据一律经 data_source_router HTTP 代理，
    不依赖本地 SDK/OpenD 连接。Facade 因此始终能将 futu 纳入候选源。
    """
    from backend.core.logger import logger
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("futu"):
        return "futu"

    adapter = FutuDataSource()
    datasource_registry.register(adapter, instance_id="default")
    logger.info("Futu 适配器已注册 (remote via data_source_router)")
    return "futu"
