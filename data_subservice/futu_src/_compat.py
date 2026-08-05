"""Futu 子服务兼容层：补齐 backend.core 中缺失的通用工具。

子服务为物理解耦的独立数据源节点，不上报主集群 Prometheus，
因此 metrics 降级为 no-op 桩；safe_float/safe_divide 等数值工具本地实现。
"""

from typing import Any

# ── 数值安全转换（复制自 backend.core.utils，去除 backend 依赖）────────


def safe_float(val: Any, default: float = 0.0) -> float:
    """安全地将值转换为 float，失败返回 default。"""
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def safe_divide(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    """安全除法，分母为 0 或非法时返回 default。"""
    try:
        denom = float(denominator)
    except (TypeError, ValueError):
        return default
    if denom == 0:
        return default
    try:
        return float(numerator) / denom
    except (TypeError, ValueError):
        return default


# ── Prometheus 指标 no-op 桩（子服务不上报主集群）────────────────────


class _GaugeNoop:
    def set(self, *args, **kwargs) -> None:  # noqa: D401
        pass


class _CounterNoop:
    def inc(self, *args, **kwargs) -> None:  # noqa: D401
        pass


FUTU_CONNECTION_STATUS = _GaugeNoop()
FUTU_RECONNECT_FAILURES = _CounterNoop()
FUTU_RECONNECT_TOTAL = _CounterNoop()
