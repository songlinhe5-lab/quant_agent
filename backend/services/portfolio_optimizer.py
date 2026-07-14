"""
TRADE-03 · 投资组合优化引擎

职责:
- Markowitz 均值-方差优化
- 风险平价 (Risk Parity)
- 最大 Sharpe 比率
- 有效前沿
- 多模型对比
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


# ── 数据模型 ──────────────────────────────────────────────────────────────────


@dataclass
class OptimizationResult:
    """优化结果"""

    weights: Dict[str, float]  # 标的 → 权重
    expected_return: float  # 预期年化收益率
    expected_volatility: float  # 预期年化波动率
    sharpe_ratio: float  # Sharpe 比率
    risk_contributions: Dict[str, float]  # 风险贡献度 (%)
    effective_n: float  # 有效持仓数 (1 / sum(w²))


# ── 优化引擎 ──────────────────────────────────────────────────────────────────


class PortfolioOptimizer:
    """
    投资组合优化引擎 (TRADE-03)。

    使用 scipy.optimize.minimize (SLSQP) 求解二次规划。
    约束: 权重和 = 1, 非负, 单只上限 (max_weight)。
    """

    ANNUALIZATION_FACTOR = 252  # 交易日

    # ── 公共接口 ─────────────────────────────────────────────────────────────

    def mean_variance(
        self,
        returns_df,
        target_return: Optional[float] = None,
        max_weight: float = 0.3,
        risk_free_rate: float = 0.02,
    ) -> OptimizationResult:
        """
        Markowitz 均值-方差优化: min(w'Sw) s.t. w'mu >= target, sum(w)=1, w>=0。

        若 target_return 为 None, 自动取最大 Sharpe 对应的收益目标。
        """
        mu, cov, symbols = self._prepare_inputs(returns_df)
        n = len(symbols)

        if target_return is None:
            # 自动: 用最大 Sharpe 结果作为目标
            ms = self._max_sharpe_solve(mu, cov, n, max_weight, risk_free_rate)
            target_return = float(mu @ ms)

        # 目标: 最小化组合方差
        def objective(w):
            return float(w @ cov @ w)

        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1},
            {"type": "ineq", "fun": lambda w: float(mu @ w) - target_return},
        ]
        bounds = [(0.0, max_weight)] * n
        w0 = np.ones(n) / n

        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = result.x if result.success else w0

        return self._build_result(w, mu, cov, symbols, risk_free_rate)

    def risk_parity(
        self,
        returns_df,
        max_weight: float = 0.5,
        risk_free_rate: float = 0.02,
    ) -> OptimizationResult:
        """
        风险平价: 每只标的贡献相同风险, w_i * (Sw)_i = w_j * (Sw)_j。
        """
        mu, cov, symbols = self._prepare_inputs(returns_df)
        n = len(symbols)
        target_rc = 1.0 / n  # 每只标的贡献 1/n 的总风险

        def objective(w):
            w = np.maximum(w, 1e-10)
            port_var = float(w @ cov @ w)
            if port_var <= 0:
                return 1e6
            marginal_risk = cov @ w
            rc = w * marginal_risk / np.sqrt(port_var)
            rc_pct = rc / rc.sum()
            # 最小化风险贡献度与目标的偏差平方和
            return float(np.sum((rc_pct - target_rc) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(1e-6, max_weight)] * n
        w0 = np.ones(n) / n

        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = result.x if result.success else w0
        w = np.maximum(w, 0)
        w = w / w.sum()

        return self._build_result(w, mu, cov, symbols, risk_free_rate)

    def max_sharpe(
        self,
        returns_df,
        risk_free_rate: float = 0.02,
        max_weight: float = 0.3,
    ) -> OptimizationResult:
        """最大 Sharpe 比率: max((w'mu - rf) / sqrt(w'Sw))。"""
        mu, cov, symbols = self._prepare_inputs(returns_df)
        n = len(symbols)

        w = self._max_sharpe_solve(mu, cov, n, max_weight, risk_free_rate)
        return self._build_result(w, mu, cov, symbols, risk_free_rate)

    def efficient_frontier(
        self,
        returns_df,
        n_points: int = 20,
        max_weight: float = 0.3,
        risk_free_rate: float = 0.02,
    ) -> List[Dict[str, Any]]:
        """
        有效前沿: 从最小方差组合到最大收益组合的 N 个点。

        Returns:
            [{"expected_return", "expected_volatility", "sharpe_ratio", "weights"}, ...]
        """
        mu, cov, symbols = self._prepare_inputs(returns_df)
        n = len(symbols)

        # 最小方差组合
        w_min = self._min_variance_solve(cov, n, max_weight)
        ret_min = float(mu @ w_min)

        # 最大收益 (上限约束下, 全仓最高收益标的)
        ret_max = float(np.max(mu))

        target_returns = np.linspace(ret_min, ret_max, n_points)
        frontier = []
        w_prev = w_min.copy()  # 热启动: 用前一个解作为初始猜测

        for target in target_returns:
            def objective(w):
                return float(w @ cov @ w)

            constraints = [
                {"type": "eq", "fun": lambda w: np.sum(w) - 1},
                {"type": "ineq", "fun": lambda w, t=target: float(mu @ w) - t},
            ]
            bounds = [(0.0, max_weight)] * n

            res = minimize(objective, w_prev, method="SLSQP", bounds=bounds, constraints=constraints)
            if res.success:
                w = res.x
                w_prev = w.copy()  # 成功时更新热启动
            else:
                # 失败时保持 w_prev 不变
                w = w_prev.copy()

            w = np.maximum(w, 0)
            w_sum = w.sum()
            if w_sum > 0:
                w = w / w_sum

            port_ret = float(mu @ w)
            port_vol = float(np.sqrt(w @ cov @ w))
            sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0

            frontier.append({
                "expected_return": round(port_ret * self.ANNUALIZATION_FACTOR, 4),
                "expected_volatility": round(port_vol * np.sqrt(self.ANNUALIZATION_FACTOR), 4),
                "sharpe_ratio": round(sharpe, 4),
                "weights": {s: round(float(w[i]), 4) for i, s in enumerate(symbols)},
            })

        return frontier

    def compare_models(
        self,
        returns_df,
        max_weight: float = 0.3,
        risk_free_rate: float = 0.02,
    ) -> Dict[str, Any]:
        """
        模型对比: 等权 vs Markowitz vs 风险平价 vs MaxSharpe。

        Returns:
            {"models": [{"name", "weights", "expected_return", ...}, ...], "best_model": str}
        """
        mu, cov, symbols = self._prepare_inputs(returns_df)
        n = len(symbols)

        models = []

        # 等权
        w_eq = np.ones(n) / n
        models.append(self._model_entry("equal_weight", w_eq, mu, cov, symbols, risk_free_rate))

        # Markowitz
        try:
            mv = self.mean_variance(returns_df, max_weight=max_weight, risk_free_rate=risk_free_rate)
            models.append(self._result_to_entry("markowitz", mv))
        except Exception as e:
            logger.warning(f"Markowitz 优化失败: {e}")

        # 风险平价
        try:
            rp = self.risk_parity(returns_df, max_weight=max_weight, risk_free_rate=risk_free_rate)
            models.append(self._result_to_entry("risk_parity", rp))
        except Exception as e:
            logger.warning(f"风险平价优化失败: {e}")

        # 最大 Sharpe
        try:
            ms = self.max_sharpe(returns_df, risk_free_rate=risk_free_rate, max_weight=max_weight)
            models.append(self._result_to_entry("max_sharpe", ms))
        except Exception as e:
            logger.warning(f"MaxSharpe 优化失败: {e}")

        # 选出 Sharpe 最高的模型
        best = max(models, key=lambda m: m["sharpe_ratio"]) if models else {}

        return {
            "models": models,
            "best_model": best.get("name", "unknown"),
        }

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _prepare_inputs(self, returns_df):
        """从 returns DataFrame 提取 mu, cov, symbols。"""

        symbols = list(returns_df.columns)
        mu = returns_df.mean().values * self.ANNUALIZATION_FACTOR
        cov = returns_df.cov().values * self.ANNUALIZATION_FACTOR
        return mu, cov, symbols

    def _max_sharpe_solve(self, mu, cov, n, max_weight, risk_free_rate):
        """求解最大 Sharpe 权重向量。"""
        def neg_sharpe(w):
            port_ret = float(mu @ w)
            port_vol = float(np.sqrt(w @ cov @ w))
            if port_vol < 1e-12:
                return 1e6
            return -(port_ret - risk_free_rate) / port_vol

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.0, max_weight)] * n
        w0 = np.ones(n) / n

        result = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = result.x if result.success else w0
        w = np.maximum(w, 0)
        w_sum = w.sum()
        if w_sum > 0:
            w = w / w_sum
        return w

    def _min_variance_solve(self, cov, n, max_weight):
        """求解最小方差权重向量。"""
        def objective(w):
            return float(w @ cov @ w)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        bounds = [(0.0, max_weight)] * n
        w0 = np.ones(n) / n

        result = minimize(objective, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        w = result.x if result.success else w0
        w = np.maximum(w, 0)
        w_sum = w.sum()
        if w_sum > 0:
            w = w / w_sum
        return w

    def _build_result(self, w, mu, cov, symbols, risk_free_rate) -> OptimizationResult:
        """构建 OptimizationResult。"""
        w = np.maximum(w, 0)
        w_sum = w.sum()
        if w_sum > 0:
            w = w / w_sum

        port_ret = float(mu @ w)
        port_var = float(w @ cov @ w)
        port_vol = np.sqrt(max(port_var, 0))
        sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0

        # 风险贡献
        marginal = cov @ w
        rc = w * marginal
        rc_total = rc.sum()
        rc_pct = (rc / rc_total * 100) if rc_total > 0 else np.zeros(len(w))

        # 有效持仓数 1 / sum(w²)
        w_sq_sum = float(np.sum(w ** 2))
        effective_n = 1 / w_sq_sum if w_sq_sum > 0 else 0

        return OptimizationResult(
            weights={s: round(float(w[i]), 4) for i, s in enumerate(symbols)},
            expected_return=round(port_ret, 4),
            expected_volatility=round(float(port_vol), 4),
            sharpe_ratio=round(float(sharpe), 4),
            risk_contributions={s: round(float(rc_pct[i]), 2) for i, s in enumerate(symbols)},
            effective_n=round(effective_n, 2),
        )

    def _model_entry(self, name, w, mu, cov, symbols, risk_free_rate) -> Dict[str, Any]:
        """构建模型对比条目。"""
        r = self._build_result(w, mu, cov, symbols, risk_free_rate)
        return self._result_to_entry(name, r)

    @staticmethod
    def _result_to_entry(name, r: OptimizationResult) -> Dict[str, Any]:
        return {
            "name": name,
            "weights": r.weights,
            "expected_return": r.expected_return,
            "expected_volatility": r.expected_volatility,
            "sharpe_ratio": r.sharpe_ratio,
            "risk_contributions": r.risk_contributions,
            "effective_n": r.effective_n,
        }


# 全局单例
portfolio_optimizer = PortfolioOptimizer()
