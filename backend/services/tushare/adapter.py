"""
Tushare DataSource Adapter（BE-ARCH-05）

将 TushareService 适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。
对齐 docs/14 §10 零侵入扩展规范：业务代码经 Registry.fetch，禁止直连 TushareService。

Tushare 作为 A股主源（机房 IP 不被东财反爬封禁），能力覆盖：
- stock_history: A股日线历史 (pro_bar/daily)
- stock_quote: A股实时行情 (rt_k 降级 daily_basic)
- fundamental: 每日指标 / 利润表 / 财务指标
- fund_flow: 沪深港通资金流向 (moneyflow_hsgt)
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
)


class TushareDataSource:
    """TushareService → DataSourceInterface 薄适配。"""

    _CATEGORY_MAP = {
        "NO_TOKEN": ErrorCategory.NORMAL,
        "RATE_LIMIT": ErrorCategory.RATE_LIMIT,
        "QUOTA_EXHAUSTED": ErrorCategory.QUOTA_EXHAUSTED,
        "IP_BLOCKED": ErrorCategory.IP_BLOCKED,
        "INIT_FAILED": ErrorCategory.NORMAL,
        "NORMAL": ErrorCategory.NORMAL,
    }

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.tushare.service import tushare_service

            self._service = tushare_service
        return self._service

    @property
    def name(self) -> str:
        return "tushare"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def capabilities(self) -> list[str]:
        return [
            "stock_history",  # 日线 pro_bar/daily
            "stock_quote",  # 实时 rt_k 降级 daily
            "fundamental",  # 每日指标/利润表/资产负债表/现金流量表/财务指标
            "fund_flow",  # 沪深港通 moneyflow_hsgt
            "stock_list",  # 股票列表 stock_basic
            "lowfreq_history",  # 周线 weekly / 月线 monthly
            "macro",  # 宏观经济 cn_gdp/cn_cpi/cn_ppi/cn_money_supply/cn_shibor
        ]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_TUSHARE_MODE", "internal")

    def is_available(self) -> bool:
        """检测 Tushare SDK 是否可用。

        主节点不安装 tushare 包时返回 False，跳过本地注册，走 HTTP 路由。
        """
        try:
            import tushare  # noqa: F401

            return bool(self._svc()._token)
        except ImportError:
            # 主节点无 tushare 包，不可直连
            return False
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        svc = self._svc()
        hs = svc.get_health_status()
        status = hs.get("status")
        healthy = status == "healthy"
        last_error = None if healthy else hs.get("message")
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=bool(svc._token),
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities, "raw_status": status},
            rate_limit_status=RateLimitStatus(
                is_throttled=False,
                throttle_until=0.0,
                estimated_rpm=0,
                estimated_limit_rpm=0,
                consecutive_rate_limits=0,
                total_rate_limits_1h=0,
                backoff_strategy="none",
                category=None,
            ),
        )

    def _to_result(self, raw: dict, action: str) -> Result:
        if raw.get("success"):
            return Result.make_success(raw.get("data"), source=self.name)
        msg = raw.get("message", "tushare fetch failed")
        cat = raw.get("category", "NORMAL")
        err_cat = self._CATEGORY_MAP.get(cat, ErrorCategory.NORMAL)
        # 权限/配额/限流类不可重试；网络/正常失败可重试
        retryable = cat not in ("NO_TOKEN", "QUOTA_EXHAUSTED", "IP_BLOCKED")
        err = ErrorInfo(
            code=cat,
            message=msg,
            retryable=retryable,
            category=err_cat,
        )
        if cat == "RATE_LIMIT":
            return Result.make_rate_limited(err, source=self.name)
        if cat == "IP_BLOCKED":
            return Result.make_error(err, source=self.name)
        if cat == "QUOTA_EXHAUSTED":
            return Result.make_error(err, source=self.name)
        return Result.make_error(err, source=self.name)

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal("UNSUPPORTED_ACTION", f"Tushare 不支持 action: {action}", retryable=False),
                source=self.name,
            )

        svc = self._svc()
        if not svc._token:
            return Result.make_error(
                ErrorInfo.normal("TUSHARE_NO_TOKEN", "TUSHARE_TOKEN 未配置", retryable=False),
                source=self.name,
            )

        try:
            if action == "stock_history":
                raw = svc.get_daily_history(
                    ticker=str(params.get("ticker", "")),
                    start_date=params.get("start_date"),
                    end_date=params.get("end_date"),
                    num=int(params.get("num", 100)),
                    adj=params.get("adj", "qfq"),
                )
            elif action == "stock_quote":
                raw = svc.get_realtime_quote(ticker=str(params.get("ticker", "")))
            elif action == "fundamental":
                sub = params.get("sub", "daily_basic")
                if sub == "income":
                    raw = svc.get_income(ticker=str(params.get("ticker", "")), period=params.get("period"))
                elif sub == "fina_indicator":
                    raw = svc.get_fina_indicator(ticker=str(params.get("ticker", "")), period=params.get("period"))
                else:
                    raw = svc.get_daily_basic(ticker=str(params.get("ticker", "")), trade_date=params.get("trade_date"))
            elif action == "fund_flow":
                raw = svc.get_moneyflow_hsgt(start_date=params.get("start_date"), end_date=params.get("end_date"))
            elif action == "stock_list":
                raw = svc.get_stock_basic(
                    list_status=params.get("list_status", "L"),
                    exchange=params.get("exchange"),
                    fields=params.get("fields"),
                )
            elif action == "lowfreq_history":
                raw = svc.get_lowfreq_history(
                    ticker=str(params.get("ticker", "")),
                    freq=params.get("freq", "weekly"),
                    start_date=params.get("start_date"),
                    end_date=params.get("end_date"),
                    num=int(params.get("num", 100)),
                )
            elif action == "macro":
                raw = svc.get_macro(
                    api_name=str(params.get("api_name", "")),
                    **{k: v for k, v in params.items() if k not in ("api_name",)},
                )
            else:  # pragma: no cover
                return Result.make_error(
                    ErrorInfo.normal("UNSUPPORTED_ACTION", f"Tushare 不支持 action: {action}", retryable=False),
                    source=self.name,
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(ErrorInfo.normal("TUSHARE_ERROR", str(e), retryable=True), source=self.name)

        return self._to_result(raw, action)


def ensure_tushare_registered(service: Optional[Any] = None) -> str:
    """幂等注册 Tushare 适配器。

    主节点无 tushare SDK 时跳过注册，走 HTTP 路由到子服务。
    """
    from backend.core.logger import logger
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("tushare"):
        return "tushare-default"

    adapter = TushareDataSource(service)
    if not adapter.is_available():
        logger.info("Tushare SDK 不可用，跳过本地注册（走 HTTP 路由）")
        return ""

    return datasource_registry.register(adapter)
