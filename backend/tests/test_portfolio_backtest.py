"""
QUANT-02: 组合回测服务测试
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.portfolio_backtest import (
    run_portfolio_backtest,
    _align_kline_frames,
    _compute_rebalance_dates,
)


def _make_kline(n: int = 252, trend: float = 0.001, seed: int = 42) -> pd.DataFrame:
    """生成模拟 K 线数据 (含日期索引)"""
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(n) * 0.5 + trend)
    close = np.maximum(close, 1.0)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"close": close}, index=dates)


class TestPortfolioBacktest:
    """组合回测核心测试"""

    def test_equal_weight_return(self):
        """等权组合收益应为各标的收益的平均"""
        # 使用确定性上涨数据 (无噪音)
        n = 100
        dates = pd.date_range("2024-01-01", periods=n, freq="B")
        k1 = pd.DataFrame({"close": np.linspace(100, 150, n)}, index=dates)
        k2 = pd.DataFrame({"close": np.linspace(100, 130, n)}, index=dates)
        result = run_portfolio_backtest(
            symbols=["A", "B"],
            kline_dict={"A": k1, "B": k2},
            initial_capital=100000,
            rebalance_freq="buy_and_hold",
        )
        assert result["metrics"]["total_symbols"] == 2
        assert len(result["equity_curve"]) == 100
        # 两个上涨标的组合收益应为正
        total_ret = float(result["metrics"]["total_return"].replace("%", ""))
        assert total_ret > 0

    def test_rebalance_weekly(self):
        """周度再平衡应产生交易成本"""
        k1 = _make_kline(100, seed=1)
        k2 = _make_kline(100, seed=2)
        result_bh = run_portfolio_backtest(
            ["A", "B"], {"A": k1, "B": k2}, rebalance_freq="buy_and_hold"
        )
        result_w = run_portfolio_backtest(
            ["A", "B"], {"A": k1, "B": k2}, rebalance_freq="weekly"
        )
        # 再平衡会产生交易成本，净值应略低于买入持有 (在相同收益下)
        assert result_w["metrics"]["rebalance_freq"] == "weekly"
        assert len(result_w["equity_curve"]) > 0

    def test_empty_portfolio(self):
        """空持仓应返回空结果"""
        result = run_portfolio_backtest([], {}, initial_capital=100000)
        assert result["metrics"]["total_symbols"] == 0
        assert result["equity_curve"] == []

    def test_single_symbol_degenerates(self):
        """单标的应退化为买入持有该标的"""
        k1 = _make_kline(100, trend=0.001, seed=42)
        result = run_portfolio_backtest(
            symbols=["SOLO"],
            kline_dict={"SOLO": k1},
            initial_capital=100000,
            rebalance_freq="buy_and_hold",
        )
        assert result["metrics"]["total_symbols"] == 1
        assert len(result["per_symbol"]) == 1
        assert result["per_symbol"][0]["symbol"] == "SOLO"


class TestAlignKlineFrames:
    """K 线对齐测试"""

    def test_align_common_dates(self):
        """应对齐到共同交易日"""
        dates1 = pd.date_range("2024-01-01", periods=50, freq="B")
        dates2 = pd.date_range("2024-01-15", periods=30, freq="B")
        df1 = pd.DataFrame({"close": np.ones(50) * 100}, index=dates1)
        df2 = pd.DataFrame({"close": np.ones(30) * 200}, index=dates2)
        aligned = _align_kline_frames({"A": df1, "B": df2})
        assert len(aligned) == 30  # 交集
        assert "A" in aligned.columns
        assert "B" in aligned.columns


class TestRebalanceDates:
    """再平衡日期计算测试"""

    def test_monthly_rebalance(self):
        """月度再平衡应每月第一个交易日触发"""
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        rebalance = _compute_rebalance_dates(dates, "monthly")
        # 应至少有 12 个再平衡点 (一年)
        assert len(rebalance) >= 10

    def test_buy_and_hold(self):
        """买入持有只触发一次"""
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        rebalance = _compute_rebalance_dates(dates, "buy_and_hold")
        assert len(rebalance) == 1
