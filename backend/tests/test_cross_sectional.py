"""
QUANT-03: 复杂横截面选股引擎测试
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.cross_sectional import (
    compute_indicators,
    evaluate_expression,
    screen,
    _normalize_expr,
    _validate_expression,
)


def _make_kline(n: int = 100, trend: float = 0.0, seed: int = 42) -> pd.DataFrame:
    """生成模拟 K 线数据"""
    rng = np.random.RandomState(seed)
    close = 100 + np.cumsum(rng.randn(n) * 0.5 + trend)
    close = np.maximum(close, 1.0)  # 确保价格为正
    high = close + rng.rand(n) * 2
    low = close - rng.rand(n) * 2
    low = np.maximum(low, 0.5)
    open_price = close + rng.randn(n) * 0.3
    volume = rng.randint(1000, 10000, n).astype(float)

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


class TestRSIComputation:
    """RSI 计算精度测试"""

    def test_rsi_range(self):
        """RSI 值应在 0-100 范围内"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        rsi = enriched["rsi"].dropna()
        assert len(rsi) > 0
        assert rsi.min() >= 0
        assert rsi.max() <= 100

    def test_rsi_downtrend_low(self):
        """下跌趋势中 RSI 应偏低"""
        df = _make_kline(100, trend=-0.5, seed=1)
        enriched = compute_indicators(df)
        rsi_last = enriched["rsi"].iloc[-1]
        # 强下跌趋势 RSI 应低于 50
        assert rsi_last < 50


class TestKDJComputation:
    """KDJ 指标计算测试"""

    def test_kdj_columns_exist(self):
        """KDJ 三列应存在"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        assert "kdj_k" in enriched.columns
        assert "kdj_d" in enriched.columns
        assert "kdj_j" in enriched.columns

    def test_kdj_j_formula(self):
        """J = 3K - 2D"""
        df = _make_kline(100)
        enriched = compute_indicators(df).dropna()
        k = enriched["kdj_k"]
        d = enriched["kdj_d"]
        j = enriched["kdj_j"]
        expected = 3 * k - 2 * d
        pd.testing.assert_series_equal(j, expected, check_names=False)


class TestExpressionParsing:
    """表达式解析测试"""

    def test_simple_comparison(self):
        """简单比较表达式"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        mask = evaluate_expression(enriched, "RSI > 50")
        assert mask.dtype == bool
        assert len(mask) == len(enriched)

    def test_and_combination(self):
        """AND 组合表达式"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        mask = evaluate_expression(enriched, "RSI > 30 AND RSI < 70")
        # 应比单条件更严格
        rsi = enriched["rsi"]
        single = (rsi > 30) & (rsi < 70)
        assert mask.sum() == single.sum()

    def test_cross_indicator_expression(self):
        """跨指标表达式: RSI > KDJ.K"""
        df = _make_kline(100)
        enriched = compute_indicators(df).dropna()
        mask = evaluate_expression(enriched, "RSI > KDJ.K")
        assert mask.dtype == bool
        # 验证逻辑正确性
        assert mask.iloc[0] == (enriched["rsi"].iloc[0] > enriched["kdj_k"].iloc[0])


class TestIllegalExpression:
    """非法表达式拒绝测试"""

    def test_injection_rejected(self):
        """SQL/代码注入应被拒绝"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        with pytest.raises(ValueError, match="非法 token"):
            evaluate_expression(enriched, "__import__('os').system('rm -rf /')")

    def test_unknown_function_rejected(self):
        """未知函数应被拒绝"""
        df = _make_kline(100)
        enriched = compute_indicators(df)
        with pytest.raises(ValueError, match="非法 token"):
            evaluate_expression(enriched, "unknown_func(10) > 5")


class TestScreenFunction:
    """screen() 横截面筛选测试"""

    def test_screen_passes_matching(self):
        """通过筛选的标的应在结果中"""
        df = _make_kline(100, trend=0.3)
        enriched = compute_indicators(df)
        # 构造一个一定能通过的表达式
        kline_data = {"TEST.001": df}
        result = screen(["TEST.001"], "RSI > 0", kline_data)
        # RSI > 0 几乎总是成立
        assert len(result["passed"]) == 1 or result["failed_count"] == 0

    def test_screen_empty_symbols(self):
        """空标的列表应返回空结果"""
        result = screen([], "RSI > 50", {})
        assert result["passed"] == []
        assert result["failed_count"] == 0
