"""
回测运行器测试：run_grid_search_backtest, run_monte_carlo_stress_test, run_batch_sandbox_backtest
"""

import numpy as np
import pandas as pd
import pytest

from backend.core.backtest import (
    run_batch_sandbox_backtest,
    run_grid_search_backtest,
    run_monte_carlo_stress_test,
)

from .conftest import _make_ohlc_data

# ─── 沙箱兼容的矢量化策略模板 ────────────────────────────────────────
VALID_STRATEGY_CODE = """
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


# ─── 辅助函数 ───────────────────────────────────────────────────────
class TestRunnerHelpers:
    def test_build_sandbox_globals(self):
        from backend.core.backtest.runners import _build_sandbox_globals

        g = _build_sandbox_globals()
        assert "np" in g
        assert "pd" in g
        assert "BaseStrategy" in g
        assert "__builtins__" in g
        assert "DataFrame" in g
        assert "Series" in g

    def test_prepare_df_basic(self):
        from backend.core.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        result = _prepare_df(df)
        assert "open" in result.columns
        assert "close" in result.columns

    def test_prepare_df_multiindex(self):
        from backend.core.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        df.columns = pd.MultiIndex.from_tuples([(c, "") for c in df.columns])
        result = _prepare_df(df)
        assert "open" in result.columns

    def test_prepare_df_duplicate_columns(self):
        from backend.core.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        df["Close_dup"] = df["Close"]
        df.columns = list(df.columns[:-1]) + ["Close"]
        result = _prepare_df(df)
        assert len([c for c in result.columns if c == "Close"]) == 1


# ─── run_grid_search_backtest ───────────────────────────────────────
class TestGridSearchBacktest:
    def test_basic_grid_search(self):
        df = _make_ohlc_data(100)
        results = run_grid_search_backtest(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            param_grid={"fast_period": [3, 5], "slow_period": [10, 15]},
            df=df,
        )
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "params" in r
            assert "metrics" in r
            assert "sharpe_ratio" in r["metrics"]
            assert "total_return" in r["metrics"]

    def test_grid_search_sorted_by_target(self):
        df = _make_ohlc_data(100)
        results = run_grid_search_backtest(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            param_grid={"fast_period": [3, 5, 7], "slow_period": [10, 15, 20]},
            df=df,
            target_metric="sharpe_ratio",
        )
        if len(results) >= 2:
            sharpes = [float(r["metrics"]["sharpe_ratio"]) for r in results]
            assert sharpes == sorted(sharpes, reverse=True)

    def test_grid_search_class_not_found(self):
        df = _make_ohlc_data(100)
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_grid_search_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="NonExistentClass",
                param_grid={"fast_period": [5]},
                df=df,
            )

    def test_grid_search_unsafe_code_rejected(self):
        df = _make_ohlc_data(100)
        with pytest.raises(ValueError):
            run_grid_search_backtest(
                source_code="import os\nclass Bad:\n    pass",
                class_name="Bad",
                param_grid={},
                df=df,
            )

    def test_grid_search_all_fail_returns_empty_or_raises(self):
        bad_code = """
class AlwaysFail:
    def __init__(self, x=1):
        self.x = x
    def _calculate_indicators(self):
        raise RuntimeError("intentional failure")
    def _generate_signals(self):
        pass
"""
        df = _make_ohlc_data(50)
        with pytest.raises(ValueError, match="全部参数组合均执行失败"):
            run_grid_search_backtest(
                source_code=bad_code,
                class_name="AlwaysFail",
                param_grid={"x": [1, 2]},
                df=df,
            )


# ─── run_monte_carlo_stress_test ────────────────────────────────────
class TestMonteCarloStressTest:
    def test_basic_monte_carlo(self):
        df = _make_ohlc_data(100)
        result = run_monte_carlo_stress_test(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            params={"fast_period": 5, "slow_period": 10},
            df=df,
            iterations=5,
            noise_level=0.5,
        )
        assert "iterations" in result
        assert result["iterations"] > 0
        assert "mean_return" in result
        assert "mean_sharpe" in result
        assert "worst_max_drawdown" in result
        assert "raw_returns" in result

    def test_monte_carlo_with_stock_features(self):
        df = _make_ohlc_data(100)
        result = run_monte_carlo_stress_test(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            params={"fast_period": 5, "slow_period": 10},
            df=df,
            iterations=3,
            stock_features={"market_cap": 1_000_000_000.0, "beta": 2.0},
        )
        assert result["iterations"] > 0

    def test_monte_carlo_class_not_found(self):
        df = _make_ohlc_data(100)
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_monte_carlo_stress_test(
                source_code=VALID_STRATEGY_CODE,
                class_name="Missing",
                params={},
                df=df,
                iterations=3,
            )

    def test_monte_carlo_noise_distributions(self):
        df = _make_ohlc_data(100)
        for dist in ["normal", "laplace", "t"]:
            result = run_monte_carlo_stress_test(
                source_code=VALID_STRATEGY_CODE,
                class_name="TestMACross",
                params={"fast_period": 5, "slow_period": 10},
                df=df,
                iterations=2,
                noise_distribution=dist,
            )
            assert result["iterations"] > 0


# ─── run_batch_sandbox_backtest ─────────────────────────────────────
class TestBatchSandboxBacktest:
    def test_empty_dfs_raises(self):
        with pytest.raises(ValueError, match="未提供任何回测数据源"):
            run_batch_sandbox_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="TestMACross",
                params={"fast_period": 5, "slow_period": 10},
                dfs={},
            )

    def test_batch_basic(self):
        dfs = {
            "AAPL": _make_ohlc_data(100),
            "GOOG": _make_ohlc_data(100),
        }
        result = run_batch_sandbox_backtest(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            params={"fast_period": 5, "slow_period": 10},
            dfs=dfs,
        )
        assert "metrics" in result
        assert "valid_tickers" in result
        assert "equity_curve" in result
        assert len(result["valid_tickers"]) > 0

    def test_batch_class_not_found(self):
        dfs = {"AAPL": _make_ohlc_data(100)}
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_batch_sandbox_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="Missing",
                params={},
                dfs=dfs,
            )

    def test_batch_skips_short_data(self):
        dfs = {
            "LONG": _make_ohlc_data(100),
            "SHORT": _make_ohlc_data(5),
        }
        result = run_batch_sandbox_backtest(
            source_code=VALID_STRATEGY_CODE,
            class_name="TestMACross",
            params={"fast_period": 5, "slow_period": 10},
            dfs=dfs,
        )
        assert "LONG" in result["valid_tickers"]
        assert "SHORT" not in result["valid_tickers"]
