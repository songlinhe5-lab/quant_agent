"""
回测运行器测试：run_grid_search_backtest, run_monte_carlo_stress_test, run_batch_sandbox_backtest
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.backtest import (
    run_batch_sandbox_backtest,
    run_grid_search_backtest,
    run_monte_carlo_stress_test,
)
from backend.backtest.runners import (  # noqa: F401
    _drive_strategy,
    _signal_entries_exits,
)

from .conftest import _make_ohlc_data


# ─── Mock VectorBT Portfolio ───────────────────────────────────────
def _mock_vectorbt_portfolio():
    """创建 Mock 的 VectorBT Portfolio"""
    mock_pf = MagicMock()

    # Mock stats() 返回值
    mock_stats = pd.Series(
        {
            "Total Return [%]": 15.5,
            "Ann. Return [%]": 12.0,
            "Sharpe Ratio": 1.5,
            "Max Drawdown [%]": -8.0,
            "Win Rate [%]": 58.0,
            "Total Trades": 25,
            "Profit Factor": 1.8,
            "Total Fees Paid": 150.0,
        }
    )
    mock_pf.stats.return_value = mock_stats

    # Mock value() 返回权益曲线
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    mock_equity = pd.Series([100000 + i * 100 for i in range(100)], index=dates)
    mock_pf.value.return_value = mock_equity

    # Mock trades.records_readable
    mock_trades_df = pd.DataFrame(
        {
            "Entry Timestamp": [dates[10], dates[30]],
            "Exit Timestamp": [dates[20], dates[50]],
            "Direction": ["Long", "Long"],
            "Size": [100, -100],
            "Avg Entry Price": [102.0, 105.0],
            "Avg Exit Price": [108.0, 103.0],
            "PnL": [600.0, -200.0],
        }
    )
    mock_pf.trades.records_readable = mock_trades_df

    return mock_pf


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
        from backend.backtest.runners import _build_sandbox_globals

        g = _build_sandbox_globals()
        assert "np" in g
        assert "pd" in g
        assert "BaseStrategy" in g
        assert "__builtins__" in g
        assert "DataFrame" in g
        assert "Series" in g

    def test_prepare_df_basic(self):
        from backend.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        result = _prepare_df(df)
        assert "open" in result.columns
        assert "close" in result.columns

    def test_prepare_df_multiindex(self):
        from backend.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        df.columns = pd.MultiIndex.from_tuples([(c, "") for c in df.columns])
        result = _prepare_df(df)
        assert "open" in result.columns

    def test_prepare_df_duplicate_columns(self):
        from backend.backtest.runners import _prepare_df

        df = pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [100]})
        df["Close_dup"] = df["Close"]
        df.columns = list(df.columns[:-1]) + ["Close"]
        result = _prepare_df(df)
        assert len([c for c in result.columns if c == "Close"]) == 1


# ─── run_grid_search_backtest ───────────────────────────────────────
class TestGridSearchBacktest:
    @patch("backend.backtest.runners.vbt")
    def test_basic_grid_search(self, mock_vbt):
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

    @patch("backend.backtest.runners.vbt")
    def test_grid_search_sorted_by_target(self, mock_vbt):
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf

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
    @patch("backend.backtest.runners.vbt")
    def test_basic_monte_carlo(self, mock_vbt):
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

    @patch("backend.backtest.runners.vbt")
    def test_monte_carlo_with_stock_features(self, mock_vbt):
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf

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

    @patch("backend.backtest.runners.vbt")
    def test_monte_carlo_noise_distributions(self, mock_vbt):
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf

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

    @patch("backend.backtest.runners.vbt")
    def test_batch_basic(self, mock_vbt):
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
        dfs = {"AAPL": _make_ohlc_data(100)}
        with pytest.raises(ValueError, match="未在代码中找到"):
            run_batch_sandbox_backtest(
                source_code=VALID_STRATEGY_CODE,
                class_name="Missing",
                params={},
                dfs=dfs,
            )

    @patch("backend.backtest.runners.vbt")
    def test_batch_skips_short_data(self, mock_vbt):
        mock_pf = _mock_vectorbt_portfolio()
        mock_vbt.Portfolio.from_signals.return_value = mock_pf

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


# ─── 策略契约：模块级 Numba 函数 + generate_signals(df) 事件契约 ─────────
class TestStrategyContract:
    """回归：optimize_strategy_parameters 曾因沙箱拦截 numba / 不支持事件契约而失败。

    模型按系统"矢量化"要求常写成「模块级 @njit 函数 + 类方法 generate_signals(df)」
    并输出稀疏 position 列 (1=买, -1=卖平多)，runners 必须兼容该契约。
    """

    def test_drive_strategy_event_contract_renames_position(self):
        # 纯 Pandas 版事件契约：generate_signals(df) 返回 position 列
        source = (
            "import pandas as pd\n"
            "import numpy as np\n"
            "class EventStrat:\n"
            "    def generate_signals(self, df):\n"
            "        df = df.copy()\n"
            "        sig = np.zeros(len(df), dtype=int)\n"
            "        # 第 20 根买入，第 60 根卖出平多\n"
            "        sig[20] = 1\n"
            "        sig[60] = -1\n"
            "        df['position'] = sig\n"
            "        return df\n"
        )
        ns = {}
        exec(source, ns)
        inst = ns["EventStrat"]()
        res_df, encoding = _drive_strategy(inst, _make_ohlc_data(120))
        assert encoding == "event"
        assert "signal" in res_df.columns  # position 已重命名为 signal
        entries, exits, short_entries, short_exits = _signal_entries_exits(res_df, encoding)
        # event 编码：1=买入触发 entries， -1=卖出平多触发 exits，不允许做空
        assert bool(entries.iloc[20]) is True
        assert bool(exits.iloc[60]) is True
        assert short_entries.sum() == 0

    def test_drive_strategy_dense_contract_still_works(self):
        # 参考策略契约 (类方法 + 稠密 signal) 必须继续可用
        source = (
            "import pandas as pd\n"
            "import numpy as np\n"
            "class DenseStrat:\n"
            "    def _calculate_indicators(self):\n"
            "        self.df['signal'] = 0\n"
            "        self.df.loc[self.df.index[10], 'signal'] = 1\n"
            "    def _generate_signals(self):\n"
            "        self.df.loc[self.df.index[50], 'signal'] = -1\n"
        )
        ns = {}
        exec(source, ns)
        inst = ns["DenseStrat"]()
        res_df, encoding = _drive_strategy(inst, _make_ohlc_data(80))
        assert encoding == "dense"
        entries, exits, short_entries, short_exits = _signal_entries_exits(res_df, encoding)
        assert bool(entries.iloc[10]) is True
        assert bool(short_entries.iloc[50]) is True  # 稠密编码下 -1 = 做空

    def test_grid_search_numba_event_contract(self):
        # 💡 端到端回归：用户原始 ChandelierExitStrategy (模块级 @njit + generate_signals)
        # 必须能跑通网格搜索并产出真实指标，不再被安全风控拦截
        numba_source = (
            "import numpy as np\n"
            "from numba import njit\n"
            "import pandas as pd\n"
            "@njit(cache=True)\n"
            "def _calculate_indicators(opens, highs, lows, closes, volumes, atr_period):\n"
            "    n = len(closes)\n"
            "    tr = np.zeros(n)\n"
            "    tr[0] = highs[0] - lows[0]\n"
            "    for i in range(1, n):\n"
            "        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))\n"
            "    atr = np.zeros(n)\n"
            "    if n > atr_period:\n"
            "        atr[atr_period-1] = np.mean(tr[:atr_period])\n"
            "        for i in range(atr_period, n):\n"
            "            atr[i] = (atr[i-1] * (atr_period - 1) + tr[i]) / atr_period\n"
            "    return tr, atr\n"
            "@njit(cache=True)\n"
            "def _generate_signals(opens, highs, lows, closes, volumes, atr, atr_period, atr_multiplier):\n"
            "    n = len(closes)\n"
            "    signals = np.zeros(n, dtype=np.int32)\n"
            "    first_valid = atr_period\n"
            "    if first_valid >= n:\n"
            "        return signals\n"
            "    in_position = False\n"
            "    highest_high = 0.0\n"
            "    for i in range(first_valid, n):\n"
            "        if not in_position:\n"
            "            signals[i] = 1\n"
            "            in_position = True\n"
            "            highest_high = highs[i]\n"
            "        else:\n"
            "            highest_high = max(highest_high, highs[i])\n"
            "            stop_price = highest_high - atr_multiplier * atr[i]\n"
            "            if lows[i] <= stop_price:\n"
            "                signals[i] = -1\n"
            "                in_position = False\n"
            "    return signals\n"
            "class ChandelierExitStrategy:\n"
            "    def __init__(self, atr_period=14, atr_multiplier=2.0):\n"
            "        self.atr_period = int(atr_period)\n"
            "        self.atr_multiplier = atr_multiplier\n"
            "    def generate_signals(self, df):\n"
            "        df = df.copy()\n"
            "        opens = df['Open'].values.astype(np.float64)\n"
            "        highs = df['High'].values.astype(np.float64)\n"
            "        lows = df['Low'].values.astype(np.float64)\n"
            "        closes = df['Close'].values.astype(np.float64)\n"
            "        volumes = df['Volume'].values.astype(np.float64) if 'Volume' in df.columns else np.zeros(len(df))\n"
            "        _, atr = _calculate_indicators(opens, highs, lows, closes, volumes, self.atr_period)\n"
            "        signals = _generate_signals(opens, highs, lows, closes, volumes, atr, self.atr_period, self.atr_multiplier)\n"
            "        df['position'] = signals\n"
            "        return df\n"
        )
        df = _make_ohlc_data(300)
        results = run_grid_search_backtest(
            df=df,
            source_code=numba_source,
            class_name="ChandelierExitStrategy",
            param_grid={"atr_period": [7, 14], "atr_multiplier": [1.5, 2.5]},
            target_metric="win_rate",
        )
        assert len(results) > 0
        for r in results:
            assert isinstance(r["metrics"]["win_rate"], str)
            assert "%" in r["metrics"]["win_rate"]
