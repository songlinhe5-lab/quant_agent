"""
回测运行器单元测试（完全 Mock 版本）
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


# ─── 沙箱兼容的矢量化策略模板 ─────────────────────────────────────
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


# ─── Mock VectorBT Portfolio ───────────────────────────────────────
def _mock_vectorbt_portfolio():
    """创建 Mock 的 VectorBT Portfolio"""
    mock_pf = MagicMock()
    
    # Mock stats() 返回值
    mock_stats = pd.Series({
        "Total Return [%]": 15.5,
        "Ann. Return [%]": 12.0,
        "Sharpe Ratio": 1.5,
        "Max Drawdown [%]": -8.0,
        "Win Rate [%]": 58.0,
        "Total Trades": 25,
        "Profit Factor": 1.8,
        "Total Fees Paid": 150.0,
    })
    mock_pf.stats.return_value = mock_stats
    
    # Mock value() 返回权益曲线
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    mock_equity = pd.Series([100000 + i * 100 for i in range(100)], index=dates)
    mock_pf.value.return_value = mock_equity
    
    # Mock trades.records_readable
    mock_trades_df = pd.DataFrame({
        "Entry Timestamp": [dates[10], dates[30]],
        "Exit Timestamp": [dates[20], dates[50]],
        "Direction": ["Long", "Long"],
        "Size": [100, -100],
        "Avg Entry Price": [102.0, 105.0],
        "Avg Exit Price": [108.0, 103.0],
        "PnL": [600.0, -200.0],
    })
    mock_pf.trades.records_readable = mock_trades_df
    
    return mock_pf


class TestGridSearchBacktestMocked:
    """测试 run_grid_search_backtest（Mock VectorBT）"""

    @patch("backend.core.backtest.runners.vbt")
    def test_basic_grid_search_mocked(self, mock_vbt):
        """测试基本的网格搜索（完全 Mock）"""
        from backend.core.backtest.runners import run_grid_search_backtest
        
        # 设置 mock
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf
        
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

    @patch("backend.core.backtest.runners.vbt")
    def test_grid_search_empty_result(self, mock_vbt):
        """测试网格搜索无结果时抛出异常"""
        from backend.core.backtest.runners import run_grid_search_backtest
        
        # 让所有组合都失败
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

    def test_grid_search_unsafe_code_rejected(self):
        """测试不安全的代码被拒绝"""
        from backend.core.backtest.runners import run_grid_search_backtest
        
        df = _make_ohlc_data(100)
        with pytest.raises(ValueError):
            run_grid_search_backtest(
                source_code="import os\nclass Bad:\n    pass",
                class_name="Bad",
                param_grid={},
                df=df,
            )


class TestMonteCarloStressTestMocked:
    """测试 run_monte_carlo_stress_test（Mock VectorBT）"""

    @patch("backend.core.backtest.runners.vbt")
    def test_basic_monte_carlo_mocked(self, mock_vbt):
        """测试基本的蒙特卡洛测试（完全 Mock）"""
        from backend.core.backtest.runners import run_monte_carlo_stress_test
        
        # 设置 mock
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf
        
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

    def test_monte_carlo_class_not_found(self):
        """测试类不存在时抛出异常"""
        from backend.core.backtest.runners import run_monte_carlo_stress_test
        
        df = _make_ohlc_data(100)
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_monte_carlo_stress_test(
                source_code=VALID_STRATEGY_CODE,
                class_name="Missing",
                params={},
                df=df,
                iterations=3,
            )


class TestBatchSandboxBacktestMocked:
    """测试 run_batch_sandbox_backtest（Mock VectorBT）"""

    def test_empty_dfs_raises(self):
        """测试空的 DataFrame 字典抛出异常"""
        from backend.core.backtest.runners import run_batch_sandbox_backtest
        
        with pytest.raises(ValueError, match="未提供任何回测数据源"):
            run_batch_sandbox_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="TestMACross",
                params={"fast_period": 5, "slow_period": 10},
                dfs={},
            )

    @patch("backend.core.backtest.runners.vbt")
    def test_batch_basic_mocked(self, mock_vbt):
        """测试基本的批量回测（完全 Mock）"""
        from backend.core.backtest.runners import run_batch_sandbox_backtest
        
        # 设置 mock
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf
        
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
        """测试类不存在时抛出异常"""
        from backend.core.backtest.runners import run_batch_sandbox_backtest
        
        dfs = {"AAPL": _make_ohlc_data(100)}
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_batch_sandbox_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="Missing",
                params={},
                dfs=dfs,
            )


class TestRunnersHelpers:
    """测试 runners.py 中的辅助函数"""

    def test_build_sandbox_globals(self):
        """测试 _build_sandbox_globals"""
        from backend.core.backtest.runners import _build_sandbox_globals
        
        g = _build_sandbox_globals()
        assert "np" in g
        assert "pd" in g
        assert "BaseStrategy" in g
        assert "__builtins__" in g
        assert "DataFrame" in g
        assert "Series" in g

    def test_prepare_df_basic(self):
        """测试 _prepare_df 基本功能"""
        from backend.core.backtest.runners import _prepare_df
        
        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        result = _prepare_df(df)
        assert "open" in result.columns
        assert "close" in result.columns

    def test_prepare_df_with_ohlc(self):
        """测试 _prepare_df 处理 OHLC 列"""
        from backend.core.backtest.runners import _prepare_df
        
        df = _make_ohlc_data(50)
        result = _prepare_df(df)
        
        # 检查是否添加了小写列
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
