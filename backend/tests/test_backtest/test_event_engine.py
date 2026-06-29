"""
事件驱动回测引擎测试：EventDrivenBacktestEngine
"""

import time
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backend.core.backtest import (
    BaseStrategySandbox,
    EventDrivenBacktestEngine,
    run_dynamic_sandbox_backtest,
)

from .conftest import _make_ohlc_data


# ─── 基础功能 ───────────────────────────────────────────────────────
class TestEventDrivenEngineBasic:
    def test_init_default_params(self, ohlc_data):
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, ohlc_data)
        assert engine.initial_capital == 100000.0
        assert engine.commission_pct == 0.0005
        assert engine.position == 0

    def test_run_data_too_short(self):
        df = _make_ohlc_data(5)
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, df)
        with pytest.raises(ValueError, match="回测数据长度不足"):
            engine.run()

    def test_execute_buy_basic(self, ohlc_data):
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, ohlc_data)
        engine._execute_buy(base_price=100.0, date_str="2024-01-10")
        assert engine.position > 0
        assert engine.trades[0]["action"] == "BUY"

    def test_execute_sell_basic(self, ohlc_data):
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, ohlc_data)
        engine._execute_buy(base_price=100.0, date_str="2024-01-10")
        engine._execute_sell(base_price=110.0, date_str="2024-01-11")
        assert engine.position == 0
        assert len(engine.trades) == 2

    def test_execute_buy_with_stop_loss(self, ohlc_data):
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, ohlc_data)
        engine._execute_buy(base_price=100.0, date_str="2024-01-10", stop_loss=95.0)
        assert strategy._position_data["stop_loss"] == 95.0

    def test_execute_sell_profit(self, ohlc_data):
        strategy = BaseStrategySandbox()
        engine = EventDrivenBacktestEngine(strategy, ohlc_data)
        engine._execute_buy(base_price=100.0, date_str="2024-01-10")
        engine._execute_sell(base_price=110.0, date_str="2024-01-11")
        assert engine.trades[1]["profit"] > 0


# ─── 策略信号 ───────────────────────────────────────────────────────
class TestEventDrivenEngineStrategies:
    def test_on_bar_strategy(self, ohlc_data):
        class SimpleStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                if not self.has_position():
                    return {"action": "buy"}
                return None

        engine = EventDrivenBacktestEngine(SimpleStrategy(), ohlc_data)
        result = engine.run()
        assert "metrics" in result
        assert len(result["trades"]) > 0

    def test_on_tick_strategy(self, ohlc_data):
        class TickStrategy(BaseStrategySandbox):
            def on_tick(self, window_df):
                if not self.has_position():
                    return {"action": "buy"}
                return None

        engine = EventDrivenBacktestEngine(TickStrategy(), ohlc_data)
        result = engine.run()
        assert "metrics" in result

    def test_debug_mode(self, ohlc_data):
        class DebugStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                if not self.has_position():
                    return {"action": "buy"}
                return None

        engine = EventDrivenBacktestEngine(DebugStrategy(), ohlc_data, debug_mode=True)
        result = engine.run()
        assert len(result["debug_logs"]) > 0

    def test_no_trade_strategy(self, ohlc_data):
        class NoTradeStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                return None

        engine = EventDrivenBacktestEngine(NoTradeStrategy(), ohlc_data)
        result = engine.run()
        assert result["metrics"]["sharpe_ratio"] == "0.00"
        assert result["metrics"]["max_drawdown"] == "0.00%"

    def test_multiindex_columns(self, ohlc_data):
        ohlc_data.columns = pd.MultiIndex.from_tuples([(col, "") for col in ohlc_data.columns])

        class HoldStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                return None

        engine = EventDrivenBacktestEngine(HoldStrategy(), ohlc_data)
        result = engine.run()
        assert "metrics" in result


# ─── 限价单与止损 ───────────────────────────────────────────────────
class TestEventDrivenEngineOrders:
    def test_limit_buy_order(self):
        dates = pd.date_range("2024-01-01", periods=15, freq="D")
        prices = [100.0] * 15
        prices[11] = 90.0
        prices[13] = 122.0

        df = pd.DataFrame(
            {
                "Open": prices,
                "High": [p + 5.0 for p in prices],
                "Low": [p - 5.0 for p in prices],
                "Close": prices,
                "Volume": [1000] * 15,
            },
            index=dates,
        )

        class LimitStrategy:
            def __init__(self):
                self._position_size = 0
                self._position_data = {}

            def on_bar(self, window_df):
                bar_index = len(window_df) - 1
                if bar_index == 10 and self._position_size == 0:
                    return {"action": "buy", "limit_price": 89.0, "stop_loss": 80.0}
                elif bar_index == 12 and self._position_size > 0:
                    return {"action": "sell", "limit_price": 121.0}
                return {}

        engine = EventDrivenBacktestEngine(LimitStrategy(), df, commission_pct=0.0, slippage_pct=0.0)
        result = engine.run()
        trades = result["trades"]
        assert len(trades) == 2
        assert trades[0]["action"] == "BUY"
        assert trades[0]["price"] == 89.0
        assert trades[1]["action"] == "SELL"
        assert trades[1]["price"] == 122.0

    def test_stop_loss(self, ohlc_data):
        ohlc_data.iloc[15, ohlc_data.columns.get_loc("Low")] = 85.0

        class StopLossStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                if not self.has_position():
                    return {"action": "buy", "stop_loss": 90.0}
                return None

        engine = EventDrivenBacktestEngine(StopLossStrategy(), ohlc_data)
        result = engine.run()
        assert "metrics" in result

    def test_cancel_order(self, ohlc_data):
        class CancelStrategy(BaseStrategySandbox):
            def on_bar(self, window_df):
                if len(window_df) == 11:
                    return {"action": "buy", "limit_price": 95.0}
                elif len(window_df) == 12:
                    return {"action": "cancel"}
                return None

        engine = EventDrivenBacktestEngine(CancelStrategy(), ohlc_data)
        result = engine.run()
        assert "metrics" in result


# ─── 确定性场景精确断言 ─────────────────────────────────────────────
class TestEventDrivenEngineDeterministic:
    def test_full_execution_cycle(self, mock_dataframe):
        class MockStrategy:
            def __init__(self):
                self._position_size = 0
                self._position_data = {}

            def on_bar(self, window_df):
                bar_index = len(window_df) - 1
                if bar_index == 11:
                    return {"action": "buy", "stop_loss": 105.0}
                elif bar_index == 15:
                    return {"action": "sell"}
                elif bar_index == 17:
                    return {"action": "buy", "stop_loss": 112.0}
                return {}

        engine = EventDrivenBacktestEngine(
            strategy_instance=MockStrategy(),
            df=mock_dataframe,
            initial_capital=100000.0,
            commission_pct=0.001,
            slippage_pct=0.001,
        )
        report = engine.run()

        assert "metrics" in report
        assert "equity_curve" in report
        assert "trades" in report
        assert len(report["trades"]) == 4
        assert report["trades"][0]["action"] == "BUY"
        assert report["trades"][1]["action"] == "SELL"
        assert report["trades"][2]["action"] == "BUY"
        assert report["trades"][3]["action"] == "SELL"

        total_friction = float(report["metrics"]["total_friction_cost"].replace("$", "").replace(",", ""))
        assert total_friction > 0.0
        assert len(report["equity_curve"]) == 10


# ─── 性能基准 ───────────────────────────────────────────────────────
class TestEventDrivenEngineBenchmark:
    def test_10k_bars_performance(self):
        np.random.seed(42)
        n_bars = 10000
        dates = pd.date_range("2010-01-01", periods=n_bars, freq="min")
        closes = np.cumprod(1 + np.random.randn(n_bars) * 0.001) * 100

        df = pd.DataFrame(
            {
                "Open": closes * 0.999,
                "High": closes * 1.002,
                "Low": closes * 0.998,
                "Close": closes,
                "Volume": np.random.randint(100, 1000, size=n_bars),
                "signal": np.zeros(n_bars),
            },
            index=dates,
        )
        df.loc[df.index[100::200], "signal"] = 1
        df.loc[df.index[200::200], "signal"] = -1

        class BenchStrategy:
            def __init__(self):
                self._position_size = 0
                self._position_data = {}

            def on_bar(self, window_df):
                sig = window_df.iloc[-1].get("signal", 0)
                if sig == 1:
                    return {"action": "buy", "stop_loss": window_df.iloc[-1]["Close"] * 0.95}
                elif sig == -1:
                    return {"action": "sell"}
                return {}

        engine = EventDrivenBacktestEngine(BenchStrategy(), df)
        start = time.perf_counter()
        engine.run()
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"EventDrivenBacktestEngine took too long: {elapsed:.4f}s"


# ─── run_dynamic_sandbox_backtest ───────────────────────────────────
VECTOR_STRATEGY_CODE = """
class MyVecStrategy:
    def __init__(self, period=5):
        self.period = period

    def _calculate_indicators(self):
        df = self.df
        df["sma"] = df["Close"].rolling(self.period).mean()
        df["atr"] = df["Close"].diff().abs().rolling(14).mean().fillna(df["Close"] * 0.01)

    def _generate_signals(self):
        df = self.df
        df["signal"] = 0
        buy = (df["Close"] > df["sma"]) & (df["Close"].shift(1) <= df["sma"].shift(1))
        sell = (df["Close"] < df["sma"]) & (df["Close"].shift(1) >= df["sma"].shift(1))
        df.loc[buy, "signal"] = 1
        df.loc[sell, "signal"] = -1
"""

EVENT_STRATEGY_CODE = """
from __future__ import annotations
class MyEventStrategy(BaseStrategy):
    def __init__(self):
        super().__init__()

    def on_bar(self, window_df):
        if not self.has_position() and len(window_df) > 15:
            return {"action": "buy"}
        elif self.has_position() and len(window_df) > 25:
            return {"action": "sell"}
        return None
"""


class TestRunDynamicSandboxBacktest:
    @pytest.mark.skip(reason="矢量化策略测试需要复杂的 VectorBT mock，暂时跳过")
    @patch("backend.core.backtest.event_engine.vbt")
    def test_vectorized_strategy(self, mock_vbt, ohlc_data):
        """测试矢量化策略（Mock VectorBT）"""
        result = run_dynamic_sandbox_backtest(
            source_code=VECTOR_STRATEGY_CODE,
            class_name="MyVecStrategy",
            params={"period": 5},
            df=ohlc_data,
        )
        assert "metrics" in result
        assert result["metrics"]["engine"] == "⚡ VectorBT"
        assert "equity_curve" in result
        assert "trades" in result

    def test_event_driven_fallback(self, ohlc_data):
        """测试事件驱动策略回退"""
        result = run_dynamic_sandbox_backtest(
            source_code=EVENT_STRATEGY_CODE,
            class_name="MyEventStrategy",
            params={},
            df=ohlc_data,
        )
        assert "metrics" in result
        assert result["metrics"]["engine"] == "🐢 Event-Driven"

    def test_debug_mode_forces_event_driven(self, ohlc_data):
        """测试调试模式强制使用事件驱动引擎"""
        result = run_dynamic_sandbox_backtest(
            source_code=EVENT_STRATEGY_CODE,
            class_name="MyEventStrategy",
            params={},
            df=ohlc_data,
            debug_mode=True,
        )
        assert result["metrics"]["engine"] == "🐢 Event-Driven"
        assert len(result.get("debug_logs", [])) > 0

    def test_class_not_found_raises(self, ohlc_data):
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_dynamic_sandbox_backtest(
                source_code=VECTOR_STRATEGY_CODE,
                class_name="NonExistent",
                params={},
                df=ohlc_data,
            )

    def test_unsafe_code_rejected(self, ohlc_data):
        with pytest.raises(ValueError):
            run_dynamic_sandbox_backtest(
                source_code="import os\nclass Bad:\n    pass",
                class_name="Bad",
                params={},
                df=ohlc_data,
            )
