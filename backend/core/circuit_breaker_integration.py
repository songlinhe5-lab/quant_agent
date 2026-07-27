"""
circuit_breaker_integration — 把统一的 CircuitBreaker 接入各数据源 Adapter 的 fetch 主路径。

背景（ARCH-02）：
    此前 `core/circuit_breaker.py` 形同摆设，各数据源在 `services/*/quote.py`、路由层等处
    手写时间戳熔断（硬编码 +60s）。现统一接入：

    - 同步路径（DataSourcePort）：backend.app.market_data_app.MarketDataService
      通过 fetch_via_breaker_sync 包装 adapter.fetch（futu / akshare / yfinance）。
    - 异步路径（DataSourceInterface）：backend.services.datasource.source_registry.DataSourceRegistry.fetch
      通过 fetch_via_breaker_async 包装 source.fetch（LegacyYFinance / Finnhub 等）。

熔断判定：
    - 调用前若熔断器 OPEN：同步返回 error DataSourceResult；异步抛出 CircuitBreakerOpenError
      （由调用方转成降级 / 错误结果），避免对熔断中服务继续施压。
    - 调用抛异常：record_failure（限流类由异常标记判定）。
    - 返回 error Result（非限流）：record_failure（失败计数 + 滑动窗口）。
    - 返回 success Result / DataSourceResult：record_success（重置）。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from backend.adapters.ports.data_source_port import DataSourceResult
from backend.core.circuit_breaker import CircuitBreakerOpenError, CircuitState, circuit_breaker


def _is_rate_limit_category(cat: Any) -> bool:
    """根据 error_category 判断是否为限流类错误（限流不计入熔断失败计数）。"""
    if cat is None:
        return False
    val = getattr(cat, "value", cat)
    if isinstance(val, str):
        return val not in ("normal", "circuit_open", None)
    return bool(val) and val != 0


def _is_success(result: Any) -> bool:
    """兼容两种 Result 形态：DataSourceResult(is_success 方法) 与 datasource.Result(is_success 属性 / status 枚举)。"""
    fn = getattr(result, "is_success", None)
    if callable(fn):
        return bool(fn())
    if isinstance(fn, bool):
        return fn
    status = getattr(result, "status", None)
    if status is None:
        return False
    return getattr(status, "value", status) == "success"


def fetch_via_breaker_sync(
    source: str,
    fetch_fn: Callable[..., Any],
    action: str,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    """包装同步 adapter.fetch（DataSourcePort / DataSourceResult）。

    返回 DataSourceResult；OPEN 时直接返回 error 结果，调用方按既有降级逻辑处理。
    """
    if circuit_breaker.get_state(source) == CircuitState.OPEN:
        return DataSourceResult.error(f"外部 API [{source}] 熔断中，跳过调用")
    try:
        result = fetch_fn(action, params or {})
    except Exception as e:  # noqa: BLE001
        circuit_breaker.record_failure(source, is_rate_limit=circuit_breaker.is_rate_limit_error(e))
        raise
    if _is_success(result):
        circuit_breaker.record_success(source)
    else:
        circuit_breaker.record_failure(
            source, is_rate_limit=_is_rate_limit_category(getattr(result, "error_category", None))
        )
    return result


async def fetch_via_breaker_async(
    source: str,
    fetch_fn: Callable[..., Any],
    action: str,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    """包装异步 source.fetch（DataSourceInterface / Result）。

    OPEN 时抛出 CircuitBreakerOpenError，由调用方转成错误结果。
    """
    if circuit_breaker.get_state(source) == CircuitState.OPEN:
        raise CircuitBreakerOpenError(msg=f"外部 API [{source}] 熔断中，跳过调用", service=source)
    try:
        result = await fetch_fn(action, params or {})
    except Exception as e:  # noqa: BLE001
        circuit_breaker.record_failure(source, is_rate_limit=circuit_breaker.is_rate_limit_error(e))
        raise
    if _is_success(result):
        circuit_breaker.record_success(source)
    else:
        circuit_breaker.record_failure(
            source, is_rate_limit=_is_rate_limit_category(getattr(result, "error_category", None))
        )
    return result
