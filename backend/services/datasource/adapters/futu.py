"""
Futu DataSource Adapter（BE-ARCH-05 注册发现扩展）
=================================================

将现有 FutuService（Futu OpenD 长连接中心）适配为 DataSourceInterface，使其可通过
``datasource_registry.register()`` 挂载，并在 COMM-01 健康度看板中被统一感知
（可挂载 + 可感知）。

设计原则（docs/14 §10）：组合（薄适配）而非改造原 futu 服务，避免破坏 legacy_market_data
路由与 OpenD 直连（BE-ARCH-01 边界）。适配器只负责协议对齐与结果转换。

节点约束：Futu OpenD 仅部署在 US-MASTER 主节点 (127.0.0.1:11111)，CN / slave 节点无
OpenD。因此 ``is_available()`` / ``health()`` 以 futu_service.status 真实状态为准——未
连接时卡片显示 disconnected，这正是健康看板的设计意图（可感知真实可用性）。
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


class FutuDataSource:
    """FutuService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.futu import futu_service

            self._service = futu_service
        return self._service

    @property
    def name(self) -> str:
        return "futu"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return [
            "QUOTE",
            "HISTORY",
            "FUND_FLOW",
            "OPTION_CHAIN",
            "FUNDAMENTAL",
        ]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_FUTU_MODE", "internal")

    def is_available(self) -> bool:
        """检测 Futu SDK 和 OpenD 连接是否可用。

        主节点无 futu-api 包或 OpenD 未连接时返回 False，跳过本地注册。
        """
        try:
            import futu  # noqa: F401

            # OpenD 已建立长连接才视为可用；slave 节点未部署 OpenD 自然返回 False
            return self._svc().status == "CONNECTED"
        except ImportError:
            # 无 futu-api 包，不可直连
            return False
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        svc = self._svc()
        connected = svc.status == "CONNECTED"
        last_error = svc.error_msg or None
        return HealthInfo(
            healthy=connected,
            mode=self.mode,
            connected=connected,
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities},
            rate_limit_status=RateLimitStatus(),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"Futu 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        svc = self._svc()
        if svc.status != "CONNECTED":
            return Result.make_error(
                ErrorInfo.normal(
                    "FUTU_DISCONNECTED",
                    svc.error_msg or "Futu OpenD 未连接",
                    retryable=True,
                ),
                source=self.name,
            )

        ticker = str(params.get("ticker", ""))
        try:
            if action == "QUOTE":
                data = await svc.get_quote(ticker)
            elif action == "HISTORY":
                data = await svc.get_history(
                    ticker,
                    ktype=str(params.get("ktype", "K_DAY")),
                    num=int(params.get("num", 60)),
                )
            elif action == "FUND_FLOW":
                data = await svc.get_fund_flow(ticker)
            elif action == "OPTION_CHAIN":
                data = await svc.get_option_chain(ticker, expiration_date=str(params.get("expiration_date", "")))
            else:  # pragma: no cover - 已被 capabilities 前置拦截
                return Result.make_error(
                    ErrorInfo.normal(
                        "UNSUPPORTED_ACTION",
                        f"Futu 不支持 action: {action}",
                        retryable=False,
                    ),
                    source=self.name,
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FUTU_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(data, dict) and data.get("status") == "success":
            return Result.make_success(data.get("data"), source=self.name)
        msg = (data.get("message") if isinstance(data, dict) else "") or "futu fetch failed"
        # 期权链(option-chain)在 Futu 侧偶发失败不应熔断整个 futu 数据源
        # (quote/history 等其它能力仍正常)，故标记为非重试类错误，避免计入熔断器。
        option_chain_non_retryable = action == "OPTION_CHAIN"
        if any(x in msg for x in ("429", "限流", "Rate limit", "Too Many", "403")):
            return Result.make_rate_limited(
                ErrorInfo.rate_limited(code="FUTU_RATE_LIMIT", message=msg),
                source=self.name,
            )
        return Result.make_error(
            ErrorInfo.normal("FUTU_FETCH_FAILED", msg, retryable=not option_chain_non_retryable),
            source=self.name,
        )


def ensure_futu_registered(service: Optional[Any] = None) -> str:
    """幂等注册 Futu 适配器到 DataSourceRegistry（可挂载）。

    主节点无 futu-api SDK 或 OpenD 未连接时跳过注册。
    """
    from backend.core.logger import logger
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("futu"):
        return "futu"

    adapter = FutuDataSource(service)
    if not adapter.is_available():
        logger.info("Futu SDK/OpenD 不可用，跳过本地注册")
        return ""

    datasource_registry.register(adapter, instance_id="default")
    return "futu"
