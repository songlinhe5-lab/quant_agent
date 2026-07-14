"""
TRADE-03 · 投资组合优化测试

5 tests: Markowitz 最优解 / 风险平价等风险贡献 / MaxSharpe 最优 / 有效前沿单调性 / 约束满足
"""

import numpy as np
import pandas as pd

from backend.services.portfolio_optimizer import PortfolioOptimizer, portfolio_optimizer

# ── 测试数据生成 ──────────────────────────────────────────────────────────────


def _make_returns(n_assets=5, n_days=252, seed=42):
    """生成带相关性的模拟日收益率。"""
    np.random.seed(seed)
    market = np.random.normal(0.0003, 0.01, n_days)
    data = {}
    for i in range(n_assets):
        beta = 0.8 + np.random.uniform(-0.3, 0.5)
        alpha = np.random.uniform(-0.0001, 0.0002)
        idio = np.random.normal(0, 0.015, n_days)
        data[f"SYM_{i}"] = alpha + beta * market + idio
    return pd.DataFrame(data)


# ── 测试类 ────────────────────────────────────────────────────────────────────


class TestMeanVariance:
    """Markowitz 均值-方差优化测试"""

    def test_weights_sum_to_one(self):
        """权重之和应为 1"""
        returns = _make_returns()
        result = portfolio_optimizer.mean_variance(returns, max_weight=0.3)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 1e-4, f"权重之和应为 1, 实际: {total}"

    def test_weights_non_negative(self):
        """权重应非负"""
        returns = _make_returns()
        result = portfolio_optimizer.mean_variance(returns, max_weight=0.3)
        for sym, w in result.weights.items():
            assert w >= -1e-6, f"{sym} 权重为负: {w}"

    def test_max_weight_constraint(self):
        """单只权重不应超过 max_weight"""
        returns = _make_returns()
        result = portfolio_optimizer.mean_variance(returns, max_weight=0.25)
        for sym, w in result.weights.items():
            assert w <= 0.25 + 1e-4, f"{sym} 权重 {w} 超过上限 0.25"


class TestRiskParity:
    """风险平价测试"""

    def test_equal_risk_contributions(self):
        """风险平价应使各标的风险贡献近似相等"""
        returns = _make_returns(n_assets=4)
        result = portfolio_optimizer.risk_parity(returns, max_weight=0.5)

        rc_values = list(result.risk_contributions.values())
        target = 100.0 / len(rc_values)

        for i, rc in enumerate(rc_values):
            assert abs(rc - target) < 15, f"风险贡献 {rc:.1f}% 偏离目标 {target:.1f}% 过多"

    def test_weights_sum_to_one(self):
        """权重之和应为 1"""
        returns = _make_returns()
        result = portfolio_optimizer.risk_parity(returns, max_weight=0.5)
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 1e-4, f"权重之和应为 1, 实际: {total}"


class TestMaxSharpe:
    """最大 Sharpe 测试"""

    def test_sharpe_positive(self):
        """最大 Sharpe 应为正 (模拟数据有正 alpha)"""
        returns = _make_returns()
        result = portfolio_optimizer.max_sharpe(returns, risk_free_rate=0.02, max_weight=0.3)
        assert result.sharpe_ratio > 0, f"Sharpe 应为正: {result.sharpe_ratio}"

    def test_max_weight_constraint(self):
        """单只权重不应超过 max_weight"""
        returns = _make_returns()
        result = portfolio_optimizer.max_sharpe(returns, risk_free_rate=0.02, max_weight=0.25)
        for sym, w in result.weights.items():
            assert w <= 0.25 + 1e-4, f"{sym} 权重 {w} 超过上限 0.25"


class TestEfficientFrontier:
    """有效前沿测试"""

    def test_frontier_monotonic_return(self):
        """有效前沿的预期收益应单调递增"""
        returns = _make_returns()
        frontier = portfolio_optimizer.efficient_frontier(returns, n_points=10, max_weight=0.3)

        assert len(frontier) == 10
        for i in range(1, len(frontier)):
            assert frontier[i]["expected_return"] >= frontier[i - 1]["expected_return"] - 0.01, (
                f"有效前沿收益不单调: {frontier[i - 1]['expected_return']} -> {frontier[i]['expected_return']}"
            )

    def test_frontier_has_weights(self):
        """每个点应包含权重"""
        returns = _make_returns()
        frontier = portfolio_optimizer.efficient_frontier(returns, n_points=5, max_weight=0.3)

        for point in frontier:
            assert "weights" in point
            assert "expected_return" in point
            assert "expected_volatility" in point
            assert "sharpe_ratio" in point


class TestCompareModels:
    """多模型对比测试"""

    def test_compare_returns_all_models(self):
        """对比应返回 4 种模型"""
        returns = _make_returns()
        comparison = portfolio_optimizer.compare_models(returns, max_weight=0.3)

        assert "models" in comparison
        assert "best_model" in comparison
        model_names = [m["name"] for m in comparison["models"]]
        assert "equal_weight" in model_names
        assert "markowitz" in model_names
        assert "risk_parity" in model_names
        assert "max_sharpe" in model_names

    def test_compare_has_metrics(self):
        """每个模型应有完整指标"""
        returns = _make_returns()
        comparison = portfolio_optimizer.compare_models(returns, max_weight=0.3)

        for m in comparison["models"]:
            assert "weights" in m
            assert "expected_return" in m
            assert "expected_volatility" in m
            assert "sharpe_ratio" in m
            assert "risk_contributions" in m
            assert "effective_n" in m

    def test_effective_n(self):
        """有效持仓数应合理 (1 ~ n)"""
        returns = _make_returns(n_assets=5)
        result = portfolio_optimizer.mean_variance(returns, max_weight=0.3)
        assert 1 <= result.effective_n <= 5, f"有效持仓数异常: {result.effective_n}"

    def test_singleton(self):
        """全局单例应可用"""
        assert portfolio_optimizer is not None
        assert isinstance(portfolio_optimizer, PortfolioOptimizer)
