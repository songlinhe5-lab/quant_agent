"""
RISK-02: Beta/Alpha 归因分析
Jensen's Alpha + Beta 贡献分解 + 超额收益归因
"""

import time
from typing import Any, Dict, List

import numpy as np

from backend.core.logger import logger


def calc_attribution(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    risk_free_rate: float = 0.04 / 252,  # 日化无风险利率
) -> Dict[str, Any]:
    """
    Jensen's Alpha 归因

    总收益 = Beta 贡献 + Alpha + 残差
    - Beta 贡献 = beta * (R_m - R_f)
    - Alpha = R_p - [R_f + beta * (R_m - R_f)]
    - 残差 = R_p - Beta 贡献 - Alpha (理论为 0)

    Returns:
        {
            alpha: float, beta: float, r_squared: float,
            beta_contrib: float, total_return: float,
            attribution: {alpha_pct, beta_pct, residual_pct},
            ts: float,
        }
    """
    if len(portfolio_returns) < 10 or len(benchmark_returns) < 10:
        return {
            "alpha": 0.0, "beta": 0.0, "r_squared": 0.0,
            "beta_contrib": 0.0, "total_return": 0.0,
            "attribution": {"alpha_pct": 0, "beta_pct": 0, "residual_pct": 0},
            "ts": time.time(),
        }

    # 对齐长度
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    rp = portfolio_returns[-min_len:]
    rm = benchmark_returns[-min_len:]

    # OLS: R_p = alpha + beta * R_m + epsilon
    slope, intercept = np.polyfit(rm, rp, 1)
    beta = float(slope)
    alpha_daily = float(intercept)

    # R-squared (拟合优度)
    ss_res = np.sum((rp - (alpha_daily + beta * rm)) ** 2)
    ss_tot = np.sum((rp - np.mean(rp)) ** 2)
    r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    # 年化
    alpha_annual = alpha_daily * 252
    total_return_annual = float(np.mean(rp) * 252)
    benchmark_return_annual = float(np.mean(rm) * 252)
    beta_contrib = beta * (benchmark_return_annual - risk_free_rate * 252)

    # 归因百分比
    if abs(total_return_annual) > 1e-8:
        alpha_pct = round(alpha_annual / total_return_annual * 100, 1)
        beta_pct = round(beta_contrib / total_return_annual * 100, 1)
        residual_pct = round(100 - alpha_pct - beta_pct, 1)
    else:
        alpha_pct = beta_pct = residual_pct = 0.0

    return {
        "alpha": round(alpha_annual, 6),
        "beta": round(beta, 4),
        "r_squared": round(r_squared, 4),
        "beta_contrib": round(beta_contrib, 6),
        "total_return": round(total_return_annual, 6),
        "benchmark_return": round(benchmark_return_annual, 6),
        "attribution": {
            "alpha_pct": alpha_pct,
            "beta_pct": beta_pct,
            "residual_pct": residual_pct,
        },
        "ts": time.time(),
    }
