"""
BT-01f · LegacyStrategyAdapter 测试

覆盖：
- LegacyStrategyAdapter: 旧策略适配
- wrap_legacy_strategy: 便捷函数

测试要求：≥70% 覆盖率
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import pytest

from backend.engine import Bar, Strategy
from backend.engine.adapters.legacy import LegacyStrategyAdapter, wrap_legacy_strategy
from backend.engine.clock import SimClock
from backend.engine.contracts import QuoteSnapshot
from backend.engine.drivers.backtest import BacktestContext
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig

# ─────────────────────────────────────────────
# 旧策略模拟
# ─────────────────────────────────────────────


class LegacyOnBarStrategy:
    """旧版 on_bar(window_df) → dict 策略"""

    def on_bar(self, window_df: pd.DataFrame) -> Dict[str, Any]:
        if len(window_df) < 5:
            return {}
        last_price = float(window_df.iloc[-1].get("close", 0))
        prev_price = float(window_df.iloc[-2].get("close", 0))

        if last_price > prev_price * 1.01:
            return {"action": "buy"}
        elif last_price < prev_price * 0.99:
            return {"action": "sell"}
        return {}


class LegacyOnTickStrategy:
    """旧版 on_tick(quote, params) → str 策略"""

    def on_tick(self, quote: Dict, params: Dict) -> Optional[str]:
        price = quote.get("last_price", 0)
        threshold = params.get("threshold", 100)

        if price < threshold:
            return "buy"
        elif price > threshold * 1.1:
            return "sell"
        return None


class LegacyVectorizedStrategy:
    """旧版矢量化策略"""

    def __init__(self):
        self.df = pd.DataFrame()

    def _calculate_indicators(self):
        if "close" not in self.df.columns and "Close" in self.df.columns:
            self.df["close"] = self.df["Close"]
        self.df["sma"] = self.df["close"].rolling(5).mean()

    def _generate_signals(self):
        self.df["signal"] = 0
        self.df.loc[self.df["close"] > self.df["sma"], "signal"] = 1
        self.df.loc[self.df["close"] < self.df["sma"], "signal"] = -1


class InvalidStrategy:
    """无效策略（无可识别接口）"""
    pass


# ─────────────────────────────────────────────
# LegacyStrategyAdapter 测试
# ─────────────────────────────────────────────


class TestLegacyStrategyAdapter:
    """LegacyStrategyAdapter 测试"""

    def test_wrap_on_bar_strategy(self):
        """包装 on_bar 策略"""
        legacy = LegacyOnBarStrategy()
        adapter = LegacyStrategyAdapter(legacy)

        assert adapter._has_on_bar is True
        assert adapter._has_vectorized is False
        assert adapter._has_on_tick is False

    def test_wrap_on_tick_strategy(self):
        """包装 on_tick 策略"""
        legacy = LegacyOnTickStrategy()
        adapter = LegacyStrategyAdapter(legacy, params={"threshold": 100})

        assert adapter._has_on_tick is True
        assert adapter._has_on_bar is False

    def test_wrap_vectorized_strategy(self):
        """包装矢量化策略"""
        legacy = LegacyVectorizedStrategy()
        adapter = LegacyStrategyAdapter(legacy)

        assert adapter._has_vectorized is True

    def test_reject_invalid_strategy(self):
        """拒绝无效策略"""
        with pytest.raises(ValueError, match="no recognized interface"):
            LegacyStrategyAdapter(InvalidStrategy())

    def test_on_bar_dispatches_buy(self):
        """on_bar 策略分发买入信号"""
        legacy = LegacyOnBarStrategy()
        adapter = LegacyStrategyAdapter(legacy)

        # 创建模拟 context
        clock = SimClock()
        broker = SimBroker(SimBrokerConfig(), initial_cash=100000.0)

        # 准备数据：最后一根 bar 价格比前一根高 2%
        dates = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
        prices = [100.0] * 8 + [100.0, 102.0]
        df = pd.DataFrame({
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000000.0] * 10,
        }, index=dates)

        ctx = BacktestContext(
            run_id="test",
            clock=clock,
            df=df,
            symbol="TEST.001",
            broker=broker,
        )
        ctx.set_cursor(9)
        clock.set(dates[9])

        bar = Bar(
            symbol="TEST.001",
            dt=dates[9],
            open=100.0,
            high=103.0,
            low=99.0,
            close=102.0,
            volume=1000000.0,
        )

        # 执行
        adapter.on_bar(ctx, bar)

        # 验证：应该产生了买入订单
        pos = broker.get_position("TEST.001")
        assert pos.qty > 0

    def test_on_tick_dispatches_buy(self):
        """on_tick 策略分发买入信号"""
        legacy = LegacyOnTickStrategy()
        adapter = LegacyStrategyAdapter(legacy, params={"threshold": 100})

        # 创建模拟 context（使用 LiveContext + 完整 gateway 配置）
        from backend.engine.clock import WallClock
        from backend.engine.drivers.live import LiveContext
        from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig
        from backend.engine.gateway import ExecutionGateway, GatewayMode, SimBrokerExecutor

        clock = WallClock()
        broker = SimBroker(SimBrokerConfig(), initial_cash=100000.0)
        # 设置一个当前 bar 给 executor
        bar_for_executor = Bar(
            symbol="TEST.001",
            dt=datetime.now(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=95.0,
            volume=1000000.0,
        )
        sim_executor = SimBrokerExecutor(broker)
        sim_executor.set_current_bar(bar_for_executor)
        gateway = ExecutionGateway(mode=GatewayMode.PAPER, sim_executor=sim_executor)

        ctx = LiveContext(
            mode="paper",
            run_id="test",
            clock=clock,
            gateway=gateway,
            symbol="TEST.001",
        )

        # 设置低价行情（低于阈值 100）
        ctx.set_latest_quote(QuoteSnapshot(
            symbol="TEST.001",
            dt=datetime.now(timezone.utc),
            price=95.0,
        ))

        bar = Bar(
            symbol="TEST.001",
            dt=datetime.now(timezone.utc),
            open=100.0,
            high=101.0,
            low=99.0,
            close=95.0,
            volume=1000000.0,
        )

        adapter.on_bar(ctx, bar)

        # 验证：on_tick 返回 "buy"，应该尝试下单
        pos = broker.get_position("TEST.001")
        assert pos.qty > 0


# ─────────────────────────────────────────────
# wrap_legacy_strategy 测试
# ─────────────────────────────────────────────


class TestWrapLegacyStrategy:
    """wrap_legacy_strategy 便捷函数测试"""

    def test_wrap_returns_adapter(self):
        """返回 LegacyStrategyAdapter"""
        legacy = LegacyOnBarStrategy()
        adapter = wrap_legacy_strategy(legacy)
        assert isinstance(adapter, LegacyStrategyAdapter)

    def test_wrap_with_params(self):
        """带参数包装"""
        legacy = LegacyOnTickStrategy()
        adapter = wrap_legacy_strategy(legacy, params={"threshold": 50})
        assert adapter._params == {"threshold": 50}

    def test_adapter_is_strategy(self):
        """适配器是 Strategy 子类"""
        legacy = LegacyOnBarStrategy()
        adapter = wrap_legacy_strategy(legacy)
        assert isinstance(adapter, Strategy)

    def test_adapter_signals_returns_none(self):
        """适配器 signals() 返回 None"""
        legacy = LegacyOnBarStrategy()
        adapter = wrap_legacy_strategy(legacy)
        # 适配器不支持矢量化，signals() 应返回 None
        result = adapter.signals(pd.DataFrame(), {})
        assert result is None
