"""
回测运行器：网格搜索、蒙特卡洛压力测试、批量回测
"""

import collections
import datetime
import itertools
import math
import random
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import vectorbt as vbt

from .sandbox import BaseStrategySandbox, SandboxTimeoutTracer
from .sandbox import SAFE_BUILTINS, _safe_stat, _verify_safe_code


def _build_sandbox_globals():
    """构建沙箱执行环境的全局命名空间"""
    return {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """兼容处理 DataFrame：附加小写 ohlcv 列"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.loc[:, ~df.columns.duplicated()].copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col.lower()] = df[col]
    return df


def run_grid_search_backtest(
    source_code: str,
    class_name: str,
    param_grid: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    target_metric: str = "sharpe_ratio",
) -> list:
    """
    基于 Numba 的极速网格搜索 (Grid Search) 回测引擎。
    自动遍历 param_grid 中的所有参数组合的笛卡尔积，返回按 target_metric 降序排列的 Top N 结果。
    """  # noqa: E501
    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = _build_sandbox_globals()

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))

    print(f"🚀 [Grid Search] 启动极速寻优！开始遍历 {len(combinations)} 组参数组合...")

    df = _prepare_df(df)

    results = []
    last_error = None
    for combo in combinations:
        params = dict(zip(keys, combo))
        try:
            with SandboxTimeoutTracer(timeout_seconds=3.0):
                strategy_instance = StrategyClass(**params)

                if not (
                    hasattr(strategy_instance, "_calculate_indicators")
                    and hasattr(strategy_instance, "_generate_signals")
                ):
                    raise ValueError(
                        "Grid Search 仅支持 Numba 矢量化策略。请让大模型实现 _calculate_indicators 等函数。"  # noqa: E501
                    )

                strategy_instance.df = df.copy()
                strategy_instance._calculate_indicators()
                strategy_instance._generate_signals()

            res_df = strategy_instance.df
            if "signal" not in res_df.columns:
                res_df["signal"] = 0
            if "atr" not in res_df.columns:
                res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

            res_df = res_df.dropna().copy()
            if len(res_df) < 10:
                raise ValueError("回测数据长度不足 (清洗 NaN 后数据少于 10 根)")

            entries = res_df["signal"] == 1
            exits = res_df["signal"] == 0
            short_entries = res_df["signal"] == -1
            short_exits = res_df["signal"] == 0

            atr_multi = params.get(
                "atr_multiplier",
                params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
            )
            sl_trail_pct = (res_df["atr"] * float(atr_multi)) / res_df["Close"]

            pf = vbt.Portfolio.from_signals(
                close=res_df["Close"],
                open=res_df["Open"],
                high=res_df["High"],
                low=res_df["Low"],
                entries=entries,
                exits=exits,
                short_entries=short_entries,
                short_exits=short_exits,
                init_cash=float(initial_capital),
                fees=0.0005,
                slippage=0.001,
                sl_trail=sl_trail_pct,
                upon_long_conflict="ignore",
                upon_short_conflict="ignore",
                freq="1D",
            )

            stats = pf.stats()
            total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
            sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
            max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
            win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
            total_trades = int(_safe_stat(stats, "Total Trades"))

            results.append(
                {
                    "params": params,
                    "raw_metrics": {
                        "total_return": total_return_val,
                        "sharpe_ratio": sharpe_ratio,
                        "max_drawdown": max_drawdown,
                        "win_rate": win_rate,
                        "total_trades": total_trades,
                    },
                }
            )
        except Exception as e:
            last_error = e
            continue

    if not results:
        if last_error is not None:
            raise ValueError(
                f"全部参数组合均执行失败，未产生有效交易。\n诊断信息: {type(last_error).__name__}: {last_error}"  # noqa: E501
            )
        return []

    results.sort(key=lambda x: x["raw_metrics"].get(target_metric, 0.0), reverse=True)

    return [
        {
            "params": r["params"],
            "metrics": {
                "total_return": f"{r['raw_metrics']['total_return'] * 100:.2f}%",
                "sharpe_ratio": f"{r['raw_metrics']['sharpe_ratio']:.2f}",
                "max_drawdown": f"{r['raw_metrics']['max_drawdown'] * 100:.2f}%",
                "win_rate": f"{r['raw_metrics']['win_rate'] * 100:.2f}%",
                "total_trades": r["raw_metrics"]["total_trades"],
            },
        }
        for r in results[:10]
    ]


def run_monte_carlo_stress_test(
    source_code: str,
    class_name: str,
    params: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    iterations: int = 100,
    noise_level: float = 1.0,
    noise_distribution: str = "laplace",
    stock_features: Optional[dict] = None,
) -> dict:
    """
    基于 Numba 引擎的蒙特卡洛压力测试 (Monte Carlo Stress Test)
    通过向历史价格注入高斯噪声，重复运行 N 次回测，评估策略在未知市场扰动下的鲁棒性。
    """
    local_scope = {}
    global_scope = _build_sandbox_globals()

    if "from __future__ import annotations" not in source_code:
        source_code = "from __future__ import annotations\n" + source_code

    _verify_safe_code(source_code)

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    df = _prepare_df(df)

    base_close = df["Close"].to_numpy(dtype=np.float64)
    returns = pd.Series(base_close).pct_change().dropna()
    hist_vol = returns.std() if len(returns) > 1 else 0.02

    results = []
    print(f"🎲 [Monte Carlo] 启动蒙特卡洛压力测试，将进行 {iterations} 次加噪模拟...")

    dynamic_noise_multiplier = 1.0
    if stock_features:
        market_cap = stock_features.get("market_cap")
        if market_cap is not None and market_cap < 2_000_000_000.0:
            dynamic_noise_multiplier *= 2.0
            print("📊 [Monte Carlo] 属性感知: 检测到小盘股 (市值 < 20亿)，环境噪音自动翻倍。")  # noqa: E501

        beta = stock_features.get("beta")
        if beta is not None and beta > 1.5:
            dynamic_noise_multiplier *= 1.5
            print("📊 [Monte Carlo] 属性感知: 检测到高波动标的 (Beta > 1.5)，环境噪音放大 50%。")  # noqa: E501

    for i in range(iterations):
        noisy_df = df.copy()
        target_std = hist_vol * noise_level * dynamic_noise_multiplier

        if noise_distribution == "laplace":
            scale = target_std / np.sqrt(2)
            noise = np.random.laplace(0, scale, len(noisy_df))
        elif noise_distribution == "t":
            scale = target_std / np.sqrt(3)
            noise = np.random.standard_t(df=3, size=len(noisy_df)) * scale
        else:
            noise = np.random.normal(0, target_std, len(noisy_df))

        noise_multiplier = 1.0 + noise

        vol_sigma = target_std * 2.0 * dynamic_noise_multiplier
        vol_mu = -0.5 * (vol_sigma**2)
        volume_multiplier = np.random.lognormal(mean=vol_mu, sigma=vol_sigma, size=len(noisy_df))

        noisy_df["Close"] = noisy_df["Close"] * noise_multiplier
        noisy_df["Open"] = noisy_df["Open"] * noise_multiplier
        noisy_df["High"] = noisy_df["High"] * noise_multiplier
        noisy_df["Low"] = noisy_df["Low"] * noise_multiplier
        if "Volume" in noisy_df.columns:
            noisy_df["Volume"] = np.maximum(1.0, noisy_df["Volume"] * volume_multiplier)

        with SandboxTimeoutTracer(timeout_seconds=3.0):
            strategy_instance = StrategyClass(**params)
            if not (
                hasattr(strategy_instance, "_calculate_indicators") and hasattr(strategy_instance, "_generate_signals")
            ):
                raise ValueError("Monte Carlo 测试仅支持 Numba 矢量化策略。")

            strategy_instance.df = noisy_df
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()
        if len(res_df) < 10:
            continue

        atr_multi = float(
            params.get(
                "atr_multiplier",
                params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
            )
        )

        entries = res_df["signal"] == 1
        short_entries = res_df["signal"] == -1
        exits = res_df["signal"] == 0
        sl_trail_pct = (res_df["atr"] * atr_multi) / res_df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=res_df["Close"],
            open=res_df["Open"],
            high=res_df["High"],
            low=res_df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=exits,
            init_cash=float(initial_capital),
            fees=0.0005,
            slippage=0.001,
            sl_trail=sl_trail_pct,
            upon_long_conflict="ignore",
            upon_short_conflict="ignore",
            freq="1D",
        )

        stats = pf.stats()
        results.append(
            {
                "total_return": _safe_stat(stats, "Total Return [%]") / 100.0,
                "sharpe_ratio": _safe_stat(stats, "Sharpe Ratio"),
                "max_drawdown": _safe_stat(stats, "Max Drawdown [%]") / 100.0,
                "win_rate": _safe_stat(stats, "Win Rate [%]") / 100.0,
                "profit_factor": _safe_stat(stats, "Profit Factor"),
                "total_trades": _safe_stat(stats, "Total Trades"),
            }
        )

    if not results:
        raise ValueError("蒙特卡洛测试失败，所有模拟均未产生有效数据。")

    returns_arr = np.array([r["total_return"] for r in results], dtype=np.float64)
    sharpes_arr = np.array([r["sharpe_ratio"] for r in results], dtype=np.float64)
    mdds_arr = np.array([r["max_drawdown"] for r in results], dtype=np.float64)
    win_rates_arr = np.array([r["win_rate"] for r in results], dtype=np.float64)
    pfs_arr = np.array([r["profit_factor"] for r in results], dtype=np.float64)
    trades_arr = np.array([r["total_trades"] for r in results], dtype=np.float64)

    return {
        "iterations": len(results),
        "mean_return": f"{np.mean(returns_arr) * 100:.2f}%",
        "median_return": f"{np.median(returns_arr) * 100:.2f}%",
        "worst_return": f"{np.min(returns_arr) * 100:.2f}%",
        "best_return": f"{np.max(returns_arr) * 100:.2f}%",
        "win_rate_of_simulations": f"{(np.sum(returns_arr > 0) / len(returns_arr)) * 100:.2f}%",  # noqa: E501
        "mean_sharpe": f"{np.mean(sharpes_arr):.2f}",
        "worst_max_drawdown": f"{np.min(mdds_arr) * 100:.2f}%",
        "mean_win_rate": f"{np.mean(win_rates_arr) * 100:.2f}%",
        "mean_profit_factor": f"{np.mean(pfs_arr):.2f}",
        "mean_total_trades": int(np.mean(trades_arr)),
        "raw_returns": returns_arr.tolist(),
        "raw_max_drawdowns": mdds_arr.tolist(),
    }


def run_batch_sandbox_backtest(
    source_code: str,
    class_name: str,
    params: dict,
    dfs: Dict[str, pd.DataFrame],
    initial_capital: float = 100000.0,
) -> dict:
    """
    基于 VectorBT 的多标的横截面批量回测引擎。
    支持对选股器 (Screener) 产出的备选池进行统一并行回测，输出合并的投资组合绩效指标。
    """
    if not dfs:
        raise ValueError("未提供任何回测数据源 (DataFrames 字典为空)")

    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = _build_sandbox_globals()

    if "from __future__ import annotations" not in source_code:
        source_code = "from __future__ import annotations\n" + source_code

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

    close_dict, open_dict, high_dict, low_dict = {}, {}, {}, {}
    entries_dict, exits_dict, short_entries_dict, short_exits_dict = {}, {}, {}, {}
    sl_trail_dict = {}

    atr_multi = float(
        params.get(
            "atr_multiplier",
            params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
        )
    )
    valid_tickers = []

    for ticker, df in dfs.items():
        if df.empty or len(df) < 10:
            continue

        df = _prepare_df(df)

        with SandboxTimeoutTracer(timeout_seconds=3.0):
            strategy_instance = StrategyClass(**params)
            if not (
                hasattr(strategy_instance, "_calculate_indicators") and hasattr(strategy_instance, "_generate_signals")
            ):
                raise ValueError("批量回测仅支持纯 Pandas Numba 矢量化策略。")

            strategy_instance.df = df
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()
        if len(res_df) < 10:
            continue

        close_dict[ticker] = res_df["Close"]
        open_dict[ticker] = res_df["Open"]
        high_dict[ticker] = res_df["High"]
        low_dict[ticker] = res_df["Low"]
        entries_dict[ticker] = res_df["signal"] == 1
        exits_dict[ticker] = res_df["signal"] == 0
        short_entries_dict[ticker] = res_df["signal"] == -1
        short_exits_dict[ticker] = res_df["signal"] == 0
        sl_trail_dict[ticker] = (res_df["atr"] * atr_multi) / res_df["Close"]

        valid_tickers.append(ticker)

    if not valid_tickers:
        raise ValueError("所有备选池标的清洗后有效数据均不足，批量回测终止。")

    close_df = pd.DataFrame(close_dict).ffill()
    open_df = pd.DataFrame(open_dict).ffill()
    high_df = pd.DataFrame(high_dict).ffill()
    low_df = pd.DataFrame(low_dict).ffill()
    entries_df = pd.DataFrame(entries_dict).fillna(False)
    exits_df = pd.DataFrame(exits_dict).fillna(False)
    short_entries_df = pd.DataFrame(short_entries_dict).fillna(False)
    short_exits_df = pd.DataFrame(short_exits_dict).fillna(False)
    sl_trail_df = pd.DataFrame(sl_trail_dict).fillna(0.02)

    per_asset_capital = initial_capital / len(valid_tickers)

    pf = vbt.Portfolio.from_signals(
        close=close_df,
        open=open_df,
        high=high_df,
        low=low_df,
        entries=entries_df,
        exits=exits_df,
        short_entries=short_entries_df,
        short_exits=short_exits_df,
        init_cash=per_asset_capital,
        fees=0.0005,
        slippage=0.001,
        sl_trail=sl_trail_df,
        upon_long_conflict="ignore",
        upon_short_conflict="ignore",
        freq="1D",
        group_by=True,
    )

    stats = pf.stats()
    total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
    sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
    max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
    win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
    profit_factor = _safe_stat(stats, "Profit Factor")
    total_trades = int(_safe_stat(stats, "Total Trades"))

    equity_s = pf.value()
    equity_curve = [{"date": str(d).split(" ")[0].split("T")[0], "equity": round(e, 2)} for d, e in equity_s.items()]

    return {
        "metrics": {
            "engine": "⚡ VectorBT (Batch Pool)",
            "total_return": f"{total_return_val * 100:.2f}%",
            "sharpe_ratio": f"{sharpe_ratio:.2f}",
            "max_drawdown": f"{max_drawdown * 100:.2f}%",
            "win_rate": f"{win_rate * 100:.2f}%",
            "profit_factor": f"{profit_factor:.2f}",
            "total_trades": total_trades,
        },
        "valid_tickers": valid_tickers,
        "equity_curve": equity_curve,
    }

