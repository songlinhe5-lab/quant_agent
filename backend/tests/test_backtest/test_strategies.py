"""
内置策略测试：DivergenceResonanceStrategy
"""

import pandas as pd
import pytest

from backend.core.backtest import DivergenceResonanceStrategy

from .conftest import _make_ohlc_data


class TestDivergenceResonanceStrategy:
    def test_init_default_params(self):
        df = _make_ohlc_data(100)
        strategy = DivergenceResonanceStrategy(df)
        assert strategy.initial_capital == 100000.0
        assert strategy.atr_multiplier == 2.0
        assert strategy.commission_pct == 0.0005
        assert strategy.slippage_pct == 0.001

    def test_init_custom_params(self):
        df = _make_ohlc_data(100)
        strategy = DivergenceResonanceStrategy(
            df,
            initial_capital=50000.0,
            atr_multiplier=3.0,
            commission_pct=0.001,
            slippage_pct=0.002,
        )
        assert strategy.initial_capital == 50000.0
        assert strategy.atr_multiplier == 3.0

    def test_calculate_indicators(self):
        df = _make_ohlc_data(100)
        strategy = DivergenceResonanceStrategy(df)
        strategy._calculate_indicators()

        for col in ["macd_diff", "macd_dea", "macd_hist", "rsi", "k", "d", "j", "atr"]:
            assert col in strategy.df.columns, f"Missing indicator column: {col}"

    def test_generate_signals(self):
        df = _make_ohlc_data(100)
        strategy = DivergenceResonanceStrategy(df)
        strategy._calculate_indicators()
        strategy._generate_signals()

        assert "signal" in strategy.df.columns
        assert set(strategy.df["signal"].unique()).issubset({-1, 0, 1})

    def test_init_with_multiindex(self):
        df = _make_ohlc_data(100)
        df.columns = pd.MultiIndex.from_tuples([(col, "") for col in df.columns])
        strategy = DivergenceResonanceStrategy(df)
        assert strategy.df.columns.nlevels == 1

    def test_init_with_duplicate_columns(self):
        df = _make_ohlc_data(100)
        df["Close_dup"] = df["Close"]
        df.columns = list(df.columns[:-1]) + ["Close"]
        strategy = DivergenceResonanceStrategy(df)
        assert "Close" in strategy.df.columns


# ─── run() 完整执行路径 ──────────────────────────────────────────────
# 标记为 slow：vectorbt 首次初始化约 2s，后续测试复用已初始化状态
@pytest.mark.slow
class TestDivergenceResonanceStrategyRun:
    def test_run_returns_metrics(self):
        df = _make_ohlc_data(50)
        strategy = DivergenceResonanceStrategy(df)
        result = strategy.run()

        assert "metrics" in result
        assert "equity_curve" in result
        assert "trades" in result
        assert "limit_orders" in result

        metrics = result["metrics"]
        for key in ["total_return", "annualized_return", "sharpe_ratio", "max_drawdown", "win_rate", "total_trades", "profit_factor", "total_friction_cost"]:
            assert key in metrics, f"Missing metric: {key}"

    def test_run_equity_curve_structure(self):
        df = _make_ohlc_data(50)
        strategy = DivergenceResonanceStrategy(df)
        result = strategy.run()

        assert len(result["equity_curve"]) > 0
        for point in result["equity_curve"]:
            assert "date" in point
            assert "equity" in point
            assert "benchmark" in point
            assert "price" in point

    def test_run_trades_structure(self):
        df = _make_ohlc_data(50)
        strategy = DivergenceResonanceStrategy(df)
        result = strategy.run()

        for trade in result["trades"]:
            assert "date" in trade
            assert "action" in trade
            assert "price" in trade
            assert "shares" in trade
            assert "profit" in trade
            assert trade["action"] in ["BUY", "SELL", "SHORT", "COVER"]

    def test_run_with_custom_params(self):
        df = _make_ohlc_data(50)
        strategy = DivergenceResonanceStrategy(df, initial_capital=50000.0, atr_multiplier=3.0)
        result = strategy.run()
        assert "metrics" in result

    def test_run_with_trending_data(self):
        """上升趋势数据应产生正收益"""
        df = _make_ohlc_data(50, start_price=50.0)
        strategy = DivergenceResonanceStrategy(df)
        result = strategy.run()
        assert isinstance(result["metrics"]["total_trades"], int)

    def test_run_multiindex_columns(self):
        df = _make_ohlc_data(50)
        df.columns = pd.MultiIndex.from_tuples([(col, "") for col in df.columns])
        strategy = DivergenceResonanceStrategy(df)
        result = strategy.run()
        assert "metrics" in result
