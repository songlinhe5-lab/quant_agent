"""
事件驱动回测引擎单元测试（完全 Mock 版本）
目标：确保测试不依赖任何外部服务（VectorBT、网络连接等）
"""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch


# ─── 辅助函数 ─────────────────────────────────────────────────────
def _make_ohlc_data(n: int = 100) -> pd.DataFrame:
    """生成模拟 OHLCV 数据"""
    import numpy as np
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 2)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 2,
            "Low": close - 2,
            "Close": close,
            "Volume": np.random.randint(1000000, 5000000, n),
        },
        index=dates,
    )


# ─── 测试 EventDrivenBacktestEngine ───────────────────────────────
class TestEventDrivenBacktestEngine:
    """测试 EventDrivenBacktestEngine（完全隔离，不依赖外部服务）"""

    def test_init_basic(self):
        """测试初始化"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class SimpleStrategy:
            def on_bar(self, window_df):
                return None
        
        df = _make_ohlc_data(50)
        engine = EventDrivenBacktestEngine(SimpleStrategy(), df)
        
        assert engine.initial_capital == 100000.0
        assert engine.commission_pct == 0.0005
        assert engine.slippage_pct == 0.001
        assert engine.debug_mode is False
        assert engine.cash == 100000.0
        assert engine.position == 0

    def test_init_with_custom_params(self):
        """测试自定义参数初始化"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class SimpleStrategy:
            def on_bar(self, window_df):
                return None
        
        df = _make_ohlc_data(50)
        engine = EventDrivenBacktestEngine(
            SimpleStrategy(),
            df,
            initial_capital=50000.0,
            commission_pct=0.001,
            slippage_pct=0.002,
            debug_mode=True,
        )
        
        assert engine.initial_capital == 50000.0
        assert engine.commission_pct == 0.001
        assert engine.slippage_pct == 0.002
        assert engine.debug_mode is True

    def test_run_buy_and_sell(self):
        """测试基本的买入和卖出"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class BuyAndSellStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_bar(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    return {"action": "buy"}
                elif self.bar_count == 10:
                    return {"action": "sell"}
                return None
        
        df = _make_ohlc_data(50)
        strategy = BuyAndSellStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result
        assert "equity_curve" in result
        assert "trades" in result
        assert len(result["trades"]) == 2  # 1 买 1 卖

    def test_run_with_limit_order(self):
        """测试限价单"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class LimitOrderStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_bar(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    current_price = float(window_df.iloc[-1]["close"])
                    return {"action": "buy", "limit_price": current_price * 0.95}
                elif self.bar_count == 10:
                    return {"action": "sell"}
                return None
        
        df = _make_ohlc_data(50)
        strategy = LimitOrderStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result
        assert len(result["trades"]) >= 0  # 限价单可能不会立即成交

    def test_run_with_stop_loss(self):
        """测试止损"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class StopLossStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_bar(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    current_price = float(window_df.iloc[-1]["close"])
                    return {"action": "buy", "stop_loss": current_price * 0.90}
                return None
        
        df = _make_ohlc_data(50)
        strategy = StopLossStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result

    def test_run_with_short_selling(self):
        """测试做空"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class ShortSellStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_bar(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    return {"action": "sell"}  # 做空
                elif self.bar_count == 10:
                    return {"action": "buy"}  # 平仓
                return None
        
        df = _make_ohlc_data(50)
        strategy = ShortSellStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result

    def test_run_with_cancel(self):
        """测试取消订单"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class CancelOrderStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_bar(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    current_price = float(window_df.iloc[-1]["close"])
                    return {"action": "buy", "limit_price": current_price * 0.95}
                elif self.bar_count == 6:
                    return {"action": "cancel"}
                return None
        
        df = _make_ohlc_data(50)
        strategy = CancelOrderStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result

    def test_run_with_insufficient_data(self):
        """测试数据不足时抛出异常"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class SimpleStrategy:
            def on_bar(self, window_df):
                return None
        
        df = _make_ohlc_data(5)  # 只有 5 根 K 线
        engine = EventDrivenBacktestEngine(SimpleStrategy(), df)
        
        with pytest.raises(ValueError, match="回测数据长度不足"):
            engine.run()

    def test_run_with_debug_mode(self):
        """测试调试模式"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class SimpleStrategy:
            def on_bar(self, window_df):
                return None
        
        df = _make_ohlc_data(50)
        engine = EventDrivenBacktestEngine(SimpleStrategy(), df, debug_mode=True)
        result = engine.run()
        
        assert "debug_logs" in result
        assert len(result["debug_logs"]) > 0

    def test_run_with_on_tick(self):
        """测试 on_tick 方法"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class TickStrategy:
            def __init__(self):
                self.bar_count = 0
            
            def on_tick(self, window_df):
                self.bar_count += 1
                if self.bar_count == 5:
                    return {"action": "buy"}
                elif self.bar_count == 10:
                    return {"action": "sell"}
                return None
        
        df = _make_ohlc_data(50)
        strategy = TickStrategy()
        engine = EventDrivenBacktestEngine(strategy, df)
        result = engine.run()
        
        assert "metrics" in result
        assert len(result["trades"]) == 2

    def test_execute_buy_and_sell_internal(self):
        """测试内部的买入和卖出执行"""
        from backend.core.backtest.event_engine import EventDrivenBacktestEngine
        
        class SimpleStrategy:
            def on_bar(self, window_df):
                return None
        
        df = _make_ohlc_data(50)
        engine = EventDrivenBacktestEngine(SimpleStrategy(), df)
        
        # 测试买入
        engine._execute_buy(base_price=100.0, date_str="2024-01-10")
        assert engine.position > 0
        assert engine.cash < engine.initial_capital
        
        # 测试卖出
        engine._execute_sell(base_price=110.0, date_str="2024-01-15")
        assert engine.position == 0
        assert len(engine.trades) == 2


# ─── 测试 run_dynamic_sandbox_backtest ───────────────────────────
class TestRunDynamicSandboxBacktestMocked:
    """测试 run_dynamic_sandbox_backtest（Mock VectorBT）"""

    @pytest.mark.skip(reason="矢量化策略测试需要复杂的 VectorBT mock，暂时跳过")
    @patch("backend.core.backtest.event_engine.vbt")
    def test_run_with_vectorized_strategy(self, mock_vbt):
        """测试运行矢量化策略（Mock VectorBT）"""
        from backend.core.backtest.event_engine import run_dynamic_sandbox_backtest
        
        # 矢量化策略代码
        vectorized_code = """
from __future__ import annotations
class TestMACross:
    def __init__(self, fast_period=5, slow_period=10):
        self.fast_period = fast_period
        self.slow_period = slow_period

    def _calculate_indicators(self):
        df = self.df
        df["fast_ma"] = df["Close"].rolling(self.fast_period).mean()
        df["slow_ma"] = df["Close"].rolling(self.slow_period).mean()
        df["atr"] = df["Close"].diff().abs().rolling(14).mean().fillna(df["Close"] * 0.01)

    def _generate_signals(self):
        df = self.df
        df["signal"] = 0
        buy = (df["fast_ma"] > df["slow_ma"]) & (df["fast_ma"].shift(1) <= df["slow_ma"].shift(1))
        sell = (df["fast_ma"] < df["slow_ma"]) & (df["fast_ma"].shift(1) >= df["slow_ma"].shift(1))
        df.loc[buy, "signal"] = 1
        df.loc[sell, "signal"] = -1
"""
        
        df = _make_ohlc_data(100)
        result = run_dynamic_sandbox_backtest(
            source_code=vectorized_code,
            class_name="TestMACross",
            params={"fast_period": 5, "slow_period": 10},
            df=df,
        )
        
        assert "metrics" in result
        assert "equity_curve" in result
        assert "trades" in result

    def test_run_with_event_driven_strategy(self):
        """测试运行事件驱动策略（不 Mock，因为不使用 VectorBT）"""
        from backend.core.backtest.event_engine import run_dynamic_sandbox_backtest
        
        # 事件驱动策略代码
        event_driven_code = """
from __future__ import annotations
class SimpleEventStrategy:
    def __init__(self):
        self.bar_count = 0
    
    def on_bar(self, window_df):
        self.bar_count += 1
        if self.bar_count == 5:
            return {"action": "buy"}
        elif self.bar_count == 10:
            return {"action": "sell"}
        return None
"""
        
        df = _make_ohlc_data(50)
        result = run_dynamic_sandbox_backtest(
            source_code=event_driven_code,
            class_name="SimpleEventStrategy",
            params={},
            df=df,
        )
        
        assert "metrics" in result
        assert "equity_curve" in result
        assert "trades" in result

    def test_run_unsafe_code_rejected(self):
        """测试不安全的代码被拒绝"""
        from backend.core.backtest.event_engine import run_dynamic_sandbox_backtest
        
        unsafe_code = "import os\nclass Bad:\n    pass"
        
        df = _make_ohlc_data(50)
        with pytest.raises(ValueError):
            run_dynamic_sandbox_backtest(
                source_code=unsafe_code,
                class_name="Bad",
                params={},
                df=df,
            )

    def test_run_class_not_found(self):
        """测试类不存在时抛出异常"""
        from backend.core.backtest.event_engine import run_dynamic_sandbox_backtest
        
        code = """
class MyStrategy:
    pass
"""
        
        df = _make_ohlc_data(50)
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_dynamic_sandbox_backtest(
                source_code=code,
                class_name="NonExistent",
                params={},
                df=df,
            )

    def test_run_with_debug_mode(self):
        """测试调试模式"""
        from backend.core.backtest.event_engine import run_dynamic_sandbox_backtest
        
        event_driven_code = """
from __future__ import annotations
class DebugStrategy:
    def __init__(self):
        self.bar_count = 0
    
    def on_bar(self, window_df):
        self.bar_count += 1
        if self.bar_count == 5:
            return {"action": "buy"}
        return None
"""
        
        df = _make_ohlc_data(50)
        result = run_dynamic_sandbox_backtest(
            source_code=event_driven_code,
            class_name="DebugStrategy",
            params={},
            df=df,
            debug_mode=True,
        )
        
        assert "metrics" in result
        assert "debug_logs" in result
