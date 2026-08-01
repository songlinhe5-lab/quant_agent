"""
FMP DataSource Adapter（BE-ARCH-05）

将 FMPService 适配为 DataSourceInterface，供 DataSourceRegistry.fetch 主路径调用。
对齐 docs/14 §10 零侵入扩展规范：业务代码经 Registry.fetch，禁止直连 FMPService。

限流说明：FMPService 内部已接入 rate_limit_registry（429/403 → on_rate_limit、成功 → on_success）。
本适配器返回 Result 时仅做语义化转换，限流退避状态以 throttler 为准（避免重复计数）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from backend.core.redis_client import redis_client
from backend.services.datasource import (
    ErrorCategory,
    ErrorInfo,
    HealthInfo,
    RateLimitStatus,
    Result,
)
from backend.services.finnhub.ws_ingest import tick_cache


async def _fmp_cache_get(symbol: str) -> Optional[dict[str, Any]]:
    """读取 COLLECTOR_FMP 盘后写入的财报缓存 (quant:fmp:{symbol}, TTL 1d)。

    命中即返回（不消耗 credit）；未命中/异常返回 None，由调用方降级 REST。
    """
    try:
        raw = await redis_client.get(f"quant:fmp:{symbol.upper()}")
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    return None


def _extract_ws_price(tick: dict[str, Any]) -> Optional[float]:
    """从 Finnhub WS tick（trade/quote 原始消息）容错提取最新价。

    trade: {"type":"trade","symbol":...,"data":[{"p":价格,...}]}
    quote: {"type":"quote","symbol":...,"dp":买价,"dc":...,"pc":前收}
    优先 trade 成交价 p，回退 quote 当前价 dp。
    """
    mtype = tick.get("type")
    if mtype == "trade":
        rows = tick.get("data") or []
        if rows and isinstance(rows[0], dict) and rows[0].get("p") is not None:
            return float(rows[0]["p"])
    if mtype == "quote":
        if tick.get("dp") is not None:
            return float(tick["dp"])
    # 兜底：任意已知价格字段
    for k in ("p", "dp", "c", "price"):
        if tick.get(k) is not None:
            try:
                return float(tick[k])
            except (TypeError, ValueError):
                continue
    return None


class FMPDataSource:
    """FMPService → DataSourceInterface 薄适配。"""

    def __init__(self, service: Any = None) -> None:
        self._service = service
        self._started_at = time.monotonic()

    def _svc(self) -> Any:
        if self._service is None:
            from backend.services.fmp.service import fmp_service

            self._service = fmp_service
        return self._service

    @property
    def name(self) -> str:
        return "fmp"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def capabilities(self) -> list[str]:
        return ["quote", "profile", "income_statement"]

    @property
    def mode(self) -> str:
        return os.getenv("DATASOURCE_FMP_MODE", "internal")

    def is_available(self) -> bool:
        try:
            self._svc()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def health(self) -> HealthInfo:
        from backend.services.datasource.registry import rate_limit_registry

        throttler = rate_limit_registry.get_throttler(self.name)
        rl = throttler.get_status()
        api_key = self._svc()._key()
        healthy = bool(api_key) and not rl.is_throttled
        last_error = None
        if not api_key:
            last_error = "FMP_API_KEY 未配置"
        elif rl.is_throttled:
            last_error = "FMP 处于限流退避期"
        return HealthInfo(
            healthy=healthy,
            mode=self.mode,
            connected=bool(api_key),
            uptime_seconds=time.monotonic() - self._started_at,
            last_error=last_error,
            stats={"capabilities": self.capabilities},
            rate_limit_status=RateLimitStatus(
                is_throttled=rl.is_throttled,
                throttle_until=rl.throttle_until,
                estimated_rpm=rl.estimated_rpm,
                estimated_limit_rpm=rl.estimated_limit_rpm,
                consecutive_rate_limits=rl.consecutive_rate_limits,
                total_rate_limits_1h=rl.total_rate_limits_1h,
                backoff_strategy=rl.backoff_strategy,
                category=rl.category,
            ),
        )

    async def fetch(self, action: str, params: dict[str, Any]) -> Result:
        if action not in self.capabilities:
            return Result.make_error(
                ErrorInfo.normal(
                    "UNSUPPORTED_ACTION",
                    f"FMP 不支持 action: {action}",
                    retryable=False,
                ),
                source=self.name,
            )

        svc = self._svc()
        if not svc._key():
            return Result.make_error(
                ErrorInfo.normal("FMP_NO_KEY", "FMP_API_KEY 未配置", retryable=False),
                source=self.name,
            )

        try:
            symbol = str(params.get("symbol", ""))
            if action == "quote":
                # 优先 Finnhub WS 实时 tick（已由 data_subservice → Redis → ws_ingest 回灌）
                # tick_cache 内部 TTL 自动失效（_TTL=5s），命中即视为实时价，不消耗 FMP credit。
                ws_tick = tick_cache.get(symbol)
                if ws_tick is not None:
                    ws_price = _extract_ws_price(ws_tick)
                    if ws_price is not None:
                        # 对齐 FMP /quote/{sym} 返回数组形状，前端/调用方无需改判。
                        quote_payload = [
                            {
                                "symbol": symbol.upper(),
                                "price": ws_price,
                                "source": "finnhub-ws",
                            }
                        ]
                        result = Result.make_success(quote_payload, source="finnhub-ws")
                        result.self_recorded = True  # 实时流，不消耗 FMP credit，不计入 throttler
                        return result
                # 未命中实时 tick → REST 快照降级（消耗 1 credit）
                data = await svc.get_quote(symbol)
            elif action == "profile":
                cached = await _fmp_cache_get(symbol)
                if cached and cached.get("profile") is not None:
                    result = Result.make_success(cached["profile"], source="fmp-cache")
                    result.self_recorded = True  # 命中本地缓存，不消耗 credit
                    return result
                data = await svc.get_profile(symbol)
            elif action == "income_statement":
                cached = await _fmp_cache_get(symbol)
                if cached and cached.get("income_statement") is not None:
                    result = Result.make_success(cached["income_statement"], source="fmp-cache")
                    result.self_recorded = True  # 命中本地缓存，不消耗 credit
                    return result
                data = await svc.get_income_statement(symbol, limit=int(params.get("limit", 4)))
            else:  # pragma: no cover - 已被 capabilities 前置拦截
                return Result.make_error(
                    ErrorInfo.normal(
                        "UNSUPPORTED_ACTION",
                        f"FMP 不支持 action: {action}",
                        retryable=False,
                    ),
                    source=self.name,
                )
        except Exception as e:  # noqa: BLE001
            return Result.make_error(
                ErrorInfo.normal("FMP_ERROR", str(e), retryable=True),
                source=self.name,
            )

        if isinstance(data, dict) and data.get("status") == "success":
            result = Result.make_success(data.get("data"), source=self.name)
            result.self_recorded = True  # FMPService 已记录 throttler(on_success)
            return result

        # 错误/降级：FMPService 内部已记录 throttler，此处仅做语义化转换
        raw_data = data if isinstance(data, dict) else {}
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
    """幂等注册 FMP 适配器到 DataSourceRegistry。"""
    from backend.services.datasource.source_registry import datasource_registry

    if datasource_registry.has("fmp"):
        return "fmp-default"
    return datasource_registry.register(FMPDataSource(service))
