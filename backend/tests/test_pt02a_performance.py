"""
PT-02a: 共享绩效指标库测试
==========================
覆盖: sharpe / max_drawdown / annualized_return / tracking_error / signal_consistency
"""
import numpy as np
import pandas as pd
import pytest

from backend.services.performance import (
    annualized_return,
    cumulative_return,
    max_drawdown,
    sharpe,
    signal_consistency,
    tracking_error,
    volatility,
    win_rate,
    active_return,
)


# ─────────────────────────────────────────
#  Sharpe
# ─────────────────────────────────────────


class TestSharpe:
    def test_known_value(self):
        """已知日收益率 → Sharpe 可验证"""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.02, 252))
        s = sharpe(returns)
        # 手动计算
        expected = returns.mean() / returns.std() * np.sqrt(252)
        assert abs(s - expected) < 1e-10

    def test_empty_returns_zero(self):
        """空序列 → 0"""
        assert sharpe(pd.Series(dtype=float)) == 0.0

    def test_single_value_returns_zero(self):
        """单值 → 0"""
        assert sharpe(pd.Series([0.01])) == 0.0

    def test_zero_std_returns_zero(self):
        """标准差为 0 → 0"""
        assert sharpe(pd.Series([0.01, 0.01, 0.01])) == 0.0


# ─────────────────────────────────────────
#  Max Drawdown
# ─────────────────────────────────────────


class TestMaxDrawdown:
    def test_known_drawdown(self):
        """已知净值序列 → 最大回撤"""
        nav = pd.Series([100, 110, 105, 90, 95, 100])
        dd = max_drawdown(nav)
        # 从 110 跌到 90: (90-110)/110 = -0.1818...
        assert abs(dd - (-20 / 110)) < 1e-6

    def test_no_drawdown(self):
        """单调上涨 → 回撤 = 0"""
        nav = pd.Series([100, 105, 110, 120])
        assert max_drawdown(nav) == 0.0

    def test_empty_returns_zero(self):
        """空序列 → 0"""
        assert max_drawdown(pd.Series(dtype=float)) == 0.0

    def test_full_loss(self):
        """净值归零 → -1.0"""
        nav = pd.Series([100, 50, 0])
        assert max_drawdown(nav) == -1.0


# ─────────────────────────────────────────
#  Annualized Return
# ─────────────────────────────────────────


class TestAnnualizedReturn:
    def test_doubles_in_year(self):
        """252 天翻倍 → ~100%"""
        nav = pd.Series([100.0] + [100.0 + i * (100 / 251) for i in range(1, 252)])
        ar = annualized_return(nav, freq=252)
        # 最终值 200, 初始 100, 252 天
        # (200/100)^(252/251) - 1 ≈ 1.006
        assert ar > 0.9 and ar < 1.1

    def test_empty_returns_zero(self):
        """空序列 → 0"""
        assert annualized_return(pd.Series(dtype=float)) == 0.0

    def test_flat_returns_zero(self):
        """净值不变 → 0%"""
        nav = pd.Series([100.0] * 10)
        assert annualized_return(nav) == 0.0


# ─────────────────────────────────────────
#  Volatility
# ─────────────────────────────────────────


class TestVolatility:
    def test_known_volatility(self):
        """已知收益率 → 波动率"""
        returns = pd.Series([0.01, -0.02, 0.015, -0.005, 0.01])
        vol = volatility(returns, freq=252)
        expected = returns.std() * np.sqrt(252)
        assert abs(vol - expected) < 1e-10

    def test_empty_returns_zero(self):
        """空序列 → 0"""
        assert volatility(pd.Series(dtype=float)) == 0.0


# ─────────────────────────────────────────
#  Win Rate
# ─────────────────────────────────────────


class TestWinRate:
    def test_all_wins(self):
        """全赢 → 1.0"""
        assert win_rate([10, 20, 30]) == 1.0

    def test_all_losses(self):
        """全亏 → 0.0"""
        assert win_rate([-10, -20]) == 0.0

    def test_mixed(self):
        """混合 → 0.5"""
        assert win_rate([10, -10, 20, -20]) == 0.5

    def test_empty(self):
        """空列表 → 0.0"""
        assert win_rate([]) == 0.0


# ─────────────────────────────────────────
#  Tracking Error
# ─────────────────────────────────────────


class TestTrackingError:
    def test_identical_returns(self):
        """完全相同 → TE = 0"""
        r = pd.Series([0.01, -0.02, 0.015, -0.005])
        assert tracking_error(r, r) == 0.0

    def test_known_te(self):
        """已知差值 → TE 可验证"""
        r_a = pd.Series([0.01, 0.02, -0.01, 0.015])
        r_b = pd.Series([0.005, 0.01, -0.005, 0.01])
        te = tracking_error(r_a, r_b)
        diff = r_a - r_b
        expected = diff.std() * np.sqrt(252)
        assert abs(te - expected) < 1e-10

    def test_empty_returns_zero(self):
        """空序列 → 0"""
        assert tracking_error(pd.Series(dtype=float), pd.Series([0.01])) == 0.0

    def test_different_lengths(self):
        """不同长度按较短对齐"""
        r_a = pd.Series([0.01, 0.02, 0.03, 0.04])
        r_b = pd.Series([0.01, 0.02])
        te = tracking_error(r_a, r_b)
        # 应只比较前 2 个
        diff = pd.Series([0.0, 0.0])
        assert te == 0.0  # 差值全为 0


# ─────────────────────────────────────────
#  Signal Consistency
# ─────────────────────────────────────────


class TestSignalConsistency:
    def test_identical_positions(self):
        """完全相同 → 1.0"""
        assert signal_consistency(["A", "B", "C"], ["A", "B", "C"]) == 1.0

    def test_no_overlap(self):
        """完全不同 → 0.0"""
        assert signal_consistency(["A", "B"], ["C", "D"]) == 0.0

    def test_partial_overlap(self):
        """部分重叠 → 0.5"""
        assert signal_consistency(["A", "B"], ["B", "C"]) == pytest.approx(1 / 3)

    def test_both_empty(self):
        """两个都空 → 1.0"""
        assert signal_consistency([], []) == 1.0


# ─────────────────────────────────────────
#  Cumulative Return
# ─────────────────────────────────────────


class TestCumulativeReturn:
    def test_starts_at_zero(self):
        """累计收益从 0 开始"""
        nav = pd.Series([100, 110, 120])
        cr = cumulative_return(nav)
        assert cr.iloc[0] == 0.0

    def test_known_values(self):
        """已知净值 → 累计收益"""
        nav = pd.Series([100, 110, 90])
        cr = cumulative_return(nav)
        assert cr.iloc[1] == pytest.approx(0.1)
        assert cr.iloc[2] == pytest.approx(-0.1)

    def test_empty_returns_empty(self):
        """空序列 → 空"""
        assert cumulative_return(pd.Series(dtype=float)).empty
