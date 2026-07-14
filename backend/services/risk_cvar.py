"""
RISK-05: CVaR (Conditional Value at Risk) 分解
Expected Shortfall + 按持仓分解贡献度 + 边际 VaR
"""

import time
from typing import Any, Dict, List

import numpy as np

from backend.core.logger import logger


def calc_cvar(returns: np.ndarray, alpha: float = 0.05) -> float:
    """
    计算 CVaR (Expected Shortfall)

    CVaR = E[r | r < VaR_alpha]
    即: 在超过 VaR 阈值的尾部区域，收益率的条件均值
    """
    if len(returns) < 2:
        return 0.0
    var_threshold = np.percentile(returns, alpha * 100)
    tail = returns[returns <= var_threshold]
    return float(np.mean(tail)) if len(tail) > 0 else float(var_threshold)


def decompose_cvar(
    positions: List[Dict],
    kline_data: Dict[str, np.ndarray],
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """
    按持仓分解 CVaR 贡献度

    Component VaR_i = w_i * E[r_i | r_portfolio < VaR_threshold]
    Marginal VaR_i = Component VaR_i / w_i

    Returns:
        {
            portfolio_cvar: float,
            var_threshold: float,
            decompositions: [{symbol, weight, cvar_contrib, marginal_var}],
            ts: float,
        }
    """
    if not positions or not kline_data:
        return {"portfolio_cvar": 0.0, "var_threshold": 0.0, "decompositions": [], "ts": time.time()}

    # 1. 计算每只股票的日收益率
    returns_dict = {}
    for ticker, closes in kline_data.items():
        if len(closes) >= 10:
            returns_dict[ticker] = np.diff(np.log(closes))

    if not returns_dict:
        return {"portfolio_cvar": 0.0, "var_threshold": 0.0, "decompositions": [], "ts": time.time()}

    # 2. 对齐长度
    min_len = min(len(r) for r in returns_dict.values())
    aligned = {t: r[-min_len:] for t, r in returns_dict.items()}

    # 3. 计算权重
    total_mv = sum(float(p.get("market_val", 0)) for p in positions if p.get("code") in aligned)
    if total_mv == 0:
        return {"portfolio_cvar": 0.0, "var_threshold": 0.0, "decompositions": [], "ts": time.time()}

    weights = {}
    for p in positions:
        code = p.get("code", "")
        if code in aligned:
            weights[code] = float(p.get("market_val", 0)) / total_mv

    # 4. 组合收益率
    portfolio_returns = np.zeros(min_len)
    for ticker, ret in aligned.items():
        portfolio_returns += ret * weights.get(ticker, 0)

    # 5. 组合 CVaR + VaR 阈值
    var_threshold = float(np.percentile(portfolio_returns, alpha * 100))
    portfolio_cvar = calc_cvar(portfolio_returns, alpha)

    # 6. 尾部事件掩码 (组合收益 < VaR 阈值的交易日)
    tail_mask = portfolio_returns <= var_threshold

    # 7. 分解各持仓的 CVaR 贡献
    decompositions = []
    for ticker in sorted(aligned.keys()):
        w = weights.get(ticker, 0)
        if w <= 0:
            continue
        # 该持仓在尾部事件日的平均收益
        tail_returns = aligned[ticker][tail_mask]
        avg_tail_ret = float(np.mean(tail_returns)) if len(tail_returns) > 0 else 0.0
        cvar_contrib = w * avg_tail_ret
        marginal_var = avg_tail_ret  # 边际 VaR = 尾部条件均值

        decompositions.append({
            "symbol": ticker,
            "weight": round(w, 4),
            "cvar_contrib": round(cvar_contrib, 6),
            "marginal_var": round(marginal_var, 6),
        })

    # 按贡献度绝对值降序
    decompositions.sort(key=lambda x: -abs(x["cvar_contrib"]))

    return {
        "portfolio_cvar": round(portfolio_cvar, 6),
        "var_threshold": round(var_threshold, 6),
        "decompositions": decompositions,
        "ts": time.time(),
    }
