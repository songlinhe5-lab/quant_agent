"""
circuit_breaker_integration — 把统一的 CircuitBreaker 接入数据源 fetch 主路径。

背景（ARCH-02）：
    异步路径（DataSourceInterface）：backend.services.datasource.source_registry.DataSourceRegistry.fetch
      通过 fetch_via_breaker_async 包装 source.fetch（LegacyYFinance / Finnhub 等）。

熔断判定：
    - 调用前若熔断器 OPEN：异步抛出 CircuitBreakerOpenError
      （由调用方转成降级 / 错误结果），避免对熔断中服务继续施压。
    - 调用抛异常：record_failure（限流类由异常标记判定）。
    - 返回 error Result（非限流）：record_failure（失败计数 + 滑动窗口）。
    - 返回 success Result：record_success（重置）。

注：同步路径（fetch_via_breaker_sync / DataSourceResult）已随旧 adapters 树废弃并删除（2026-08-07）。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

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
    """Result.is_success 属性检测（新树统一形态）。"""
    return bool(getattr(result, "is_success", False))


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
