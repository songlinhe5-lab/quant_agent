"""
AKShare DataSource Adapter（BE-ARCH-05 注册发现扩展）
====================================================

将现有 AKShareService（东方财富 / 沪深港通资金流向 + 宏观日历）适配为 DataSourceInterface，
使其可通过 ``datasource_registry.register()`` 挂载，并在 COMM-01 健康度看板中被统一感知
（可挂载 + 可感知）。

设计原则（docs/14 §10）：组合（薄适配）而非改造原 akshare 服务（BE-ARCH-01 边界）。适配器
只负责协议对齐与结果转换。

节点约束：AKShare 仅部署在 CN-AKSHARE 节点（北京 VPS），US-MASTER 等节点以 cache 模式仅读
Redis 中继缓存。``is_available()`` / ``health()`` 以 akshare_service.get_health_status()
的熔断器状态为准，可感知真实可用性。
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


class AKShareDataSource:
    """AKShareService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.akshare import akshare_service

            self._service = akshare_service
        return self._service

    @property
    def name(self) -> str:
        return "akshare"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return [
            "FUND_FLOW",
            "ECONOMIC_CALENDAR",
        ]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_AKSHARE_MODE", "internal")

    def is_available(self) -> bool:
        """检测 AKShare SDK 是否可用。

        主节点不安装 akshare 包时返回 False，跳过本地注册，走 HTTP 路由。
        """
        try:
            import akshare  # noqa: F401

            return self._svc().get_health_status().get("status") != "circuit_open"
        except ImportError:
            # 主节点无 akshare 包，不可直连
            return False
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        svc = self._svc()
        hs = svc.get_health_status()
        status = hs.get("status", "unknown")
        connected = status in ("healthy", "warning", "recovering")
        last_error = None if status == "healthy" else hs.get("message")
        rl = RateLimitStatus()
        cb_state = getattr(svc, "cb", None)
        if cb_state is not None:
            state = cb_state.get_state("akshare_api")
            rl.is_throttled = state.value == "open"
            rl.backoff_strategy = "circuit_breaker"
        return HealthInfo(
            healthy=status == "healthy",
            mode=hs.get("mode", self.mode),
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities, "raw_status": status},
            rate_limit_status=rl,
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"AKShare 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        svc = self._svc()
        try:
            if action == "FUND_FLOW":
                # 默认南向资金（港股通）；可传 direction=northbound/connect
                direction = str(params.get("direction", "southbound"))
                if direction == "northbound":
                    data = await svc.get_northbound_flow()
                elif direction == "connect":
                    data = await svc.get_hk_stock_connect_flow()
                else:
                    data = await svc.get_southbound_flow()
            elif action == "ECONOMIC_CALENDAR":
                data = await svc.get_economic_calendar(
                    days_ahead=int(params.get("days_ahead", 7)),
                    days_back=int(params.get("days_back", 0)),
                    skip_cache=bool(params.get("skip_cache", False)),
                )
            else:  # pragma: no cover - 已被 capabilities 前置拦截
                return Result.make_error(
                    ErrorInfo.normal(
                        "UNSUPPORTED_ACTION",
                        f"AKShare 不支持 action: {action}",
                        retryable=False,
                    ),
                    source=self.name,
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("AKSHARE_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        msg = (data.get("message") if isinstance(data, dict) else "") or "akshare fetch failed"
        if "熔断" in msg or "circuit" in msg.lower():
            return Result.make_error(
                ErrorInfo.normal("AKSHARE_CIRCUIT_OPEN", msg, retryable=True),
                source=self.name,
            )
        return Result.make_error(
            ErrorInfo.normal("AKSHARE_FETCH_FAILED", msg, retryable=True),
            source=self.name,
        )


def ensure_akshare_registered(service: Optional[Any] = None) -> str:
    """幂等注册 AKShare 适配器到 DataSourceRegistry（可挂载）。

    主节点无 akshare SDK 时跳过注册，走 HTTP 路由到子服务。
    """
    from backend.core.logger import logger
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("akshare"):
        return "akshare"

    adapter = AKShareDataSource(service)
    if not adapter.is_available():
        logger.info("AKShare SDK 不可用，跳过本地注册（走 HTTP 路由）")
        return ""

    datasource_registry.register(adapter, instance_id="default")
    return "akshare"
