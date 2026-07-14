"""
BT-01f · 旧策略契约适配器

将旧版策略接口（_calculate_indicators + _generate_signals / on_bar(window_df)）
包装为新的 Strategy 契约，实现双轨过渡。

设计文档：docs/15. 回测实盘同构引擎设计.md §六
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from backend.engine.contracts import Bar, OrderIntent, OrderUpdate
from backend.engine.strategy import Strategy

if TYPE_CHECKING:
    from backend.engine.context import StrategyContext

logger = logging.getLogger(__name__)


class LegacyStrategyAdapter(Strategy):
    """旧策略 → 新契约适配器

    支持三种旧策略接口：
    1. _calculate_indicators() + _generate_signals() → signal 列
    2. on_bar(window_df) → dict{action, ...}
    3. on_tick(quote, params) → str

    适配器将旧接口桥接到新的 on_bar(ctx, bar) 语义。
    """

    def __init__(
        self,
        legacy_instance: Any,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Args:
            legacy_instance: 旧策略实例（需有 on_bar/on_tick/_generate_signals 之一）
            params: 策略参数
        """
        self._legacy = legacy_instance
        self._params = params or {}
        self._signal_cache: Dict[str, int] = {}  # symbol → signal

        # 检测旧策略类型
        self._has_vectorized = (
            hasattr(legacy_instance, "_calculate_indicators")
            and hasattr(legacy_instance, "_generate_signals")
        )
        self._has_on_bar = hasattr(legacy_instance, "on_bar")
        self._has_on_tick = hasattr(legacy_instance, "on_tick")

        if not any([self._has_vectorized, self._has_on_bar, self._has_on_tick]):
            raise ValueError(
                f"Legacy strategy {type(legacy_instance).__name__} has no recognized interface"
            )

    def on_init(self, ctx: "StrategyContext") -> None:
        """初始化：设置 legacy 实例的 df 属性（如果支持矢量化）"""
        if self._has_vectorized:
            # 矢量化策略需要 df 属性
            history = ctx.history(ctx._subscribed_symbols[0] if hasattr(ctx, "_subscribed_symbols") else "", 1000)
            if not history.empty:
                self._legacy.df = history

    def on_bar(self, ctx: "StrategyContext", bar: Bar) -> None:
        """适配 on_bar：将新契约桥接到旧接口"""
        if self._has_on_bar and not self._has_vectorized:
            # 事件驱动旧策略：on_bar(window_df) → dict
            window = ctx.history(bar.symbol, 100)
            if window.empty:
                return

            signal = self._legacy.on_bar(window)
            if signal and isinstance(signal, dict):
                self._dispatch_legacy_signal(signal, ctx, bar)

        elif self._has_on_tick:
            # 实盘旧策略：on_tick(quote, params) → str
            quote = ctx.quote(bar.symbol)
            quote_dict = {
                "last_price": quote.price,
                "symbol": quote.symbol,
            }
            result = self._legacy.on_tick(quote_dict, self._params)
            if result and isinstance(result, str):
                # 将字符串信号转为订单
                action = result.lower()
                if action in ("buy", "long") and ctx.position(bar.symbol).is_flat:
                    ctx.order(OrderIntent(symbol=bar.symbol, side="BUY", qty=100))
                elif action in ("sell", "close", "short") and not ctx.position(bar.symbol).is_flat:
                    pos = ctx.position(bar.symbol)
                    ctx.order(OrderIntent(symbol=bar.symbol, side="SELL", qty=pos.qty))

        elif self._has_vectorized:
            # 矢量化策略：更新 df 并检查最新信号
            if hasattr(self._legacy, "df") and not self._legacy.df.empty:
                # 追加新 bar
                new_row = pd.DataFrame([{
                    "Open": bar.open,
                    "High": bar.high,
                    "Low": bar.low,
                    "Close": bar.close,
                    "Volume": bar.volume,
                }], index=[bar.dt])
                self._legacy.df = pd.concat([self._legacy.df, new_row])

                # 检查最新信号
                if "signal" in self._legacy.df.columns:
                    latest_signal = int(self._legacy.df["signal"].iloc[-1])
                    prev_signal = int(self._legacy.df["signal"].iloc[-2]) if len(self._legacy.df) > 1 else 0

                    if latest_signal != prev_signal:
                        self._dispatch_vectorized_signal(latest_signal, ctx, bar)

    def _dispatch_legacy_signal(self, signal: Dict[str, Any], ctx: "StrategyContext", bar: Bar) -> None:
        """分发旧策略信号"""
        action = str(signal.get("action", "")).lower()
        limit_price = signal.get("limit_price")
        stop_loss = signal.get("stop_loss")

        if action == "buy" and ctx.position(bar.symbol).is_flat:
            intent = OrderIntent(
                symbol=bar.symbol,
                side="BUY",
                qty=100,  # 默认数量
                order_type="LIMIT" if limit_price else "MARKET",
                limit_price=float(limit_price) if limit_price else None,
                stop_loss=float(stop_loss) if stop_loss else None,
                tag="legacy",
            )
            ctx.order(intent)

        elif action in ("sell", "close") and not ctx.position(bar.symbol).is_flat:
            pos = ctx.position(bar.symbol)
            intent = OrderIntent(
                symbol=bar.symbol,
                side="SELL",
                qty=pos.qty,
                order_type="LIMIT" if limit_price else "MARKET",
                limit_price=float(limit_price) if limit_price else None,
                tag="legacy",
            )
            ctx.order(intent)

        elif action == "cancel":
            # 取消所有挂单
            for order in ctx.open_orders():
                ctx.cancel(order.order_id)

    def _dispatch_vectorized_signal(self, signal: int, ctx: "StrategyContext", bar: Bar) -> None:
        """分发矢量化策略信号"""
        pos = ctx.position(bar.symbol)

        if signal == 1 and pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="BUY", qty=100, tag="vectorized"))
        elif signal == -1 and not pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="SELL", qty=pos.qty, tag="vectorized"))

    @classmethod
    def signals(cls, df: pd.DataFrame, params: Dict[str, Any]) -> Optional[pd.Series]:
        """适配器不支持矢量化快路径"""
        return None


def wrap_legacy_strategy(
    legacy_instance: Any,
    params: Optional[Dict[str, Any]] = None,
) -> LegacyStrategyAdapter:
    """便捷函数：将旧策略实例包装为新契约

    Args:
        legacy_instance: 旧策略实例
        params: 策略参数

    Returns:
        LegacyStrategyAdapter
    """
    return LegacyStrategyAdapter(legacy_instance, params)
