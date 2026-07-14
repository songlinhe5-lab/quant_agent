"""
TRADE-01 · 期权定价引擎

Black-Scholes 定价 + Greeks + 隐含波动率 + IV Rank/Percentile + 波动率微笑
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from scipy.stats import norm

logger = logging.getLogger(__name__)


@dataclass
class OptionGreeks:
    """期权 Greeks"""

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "delta": round(self.delta, 4),
            "gamma": round(self.gamma, 6),
            "vega": round(self.vega, 4),
            "theta": round(self.theta, 4),
            "rho": round(self.rho, 4),
        }


@dataclass
class OptionScreenResult:
    """期权筛选结果"""

    symbol: str
    strike: float
    expiry: str
    option_type: str
    iv: float
    iv_rank: float
    iv_percentile: float
    greeks: OptionGreeks
    bid: float
    ask: float
    volume: int
    open_interest: int


# ===== Black-Scholes 定价 =====


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    """
    Black-Scholes 期权定价。

    Args:
        S: 标的价格
        K: 行权价
        T: 到期时间 (年)
        r: 无风险利率
        sigma: 波动率
        option_type: "call" 或 "put"

    Returns:
        期权理论价格
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # 边界情况
        if T <= 0:
            if option_type.lower() == "call":
                return max(S - K, 0)
            else:
                return max(K - S, 0)
        return 0.0

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type.lower() == "call":
        price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    else:
        price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    return max(price, 0.0)


# ===== Greeks 计算 =====


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> OptionGreeks:
    """
    计算期权 Greeks。

    Returns:
        OptionGreeks: delta, gamma, vega, theta, rho
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        # 到期时 Greeks
        max(S - K, 0)
        max(K - S, 0)
        if option_type.lower() == "call":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return OptionGreeks(delta=delta, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Gamma (Call 和 Put 相同)
    gamma = norm.pdf(d1) / (S * sigma * sqrt_T)

    # Vega (Call 和 Put 相同, 每 1% 波动率变化的价格变化)
    vega = S * norm.pdf(d1) * sqrt_T / 100

    if option_type.lower() == "call":
        delta = norm.cdf(d1)
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt_T) - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365  # 每日
        rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100  # 每 1% 利率变化
    else:
        delta = norm.cdf(d1) - 1
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * sqrt_T) + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
        rho = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100

    return OptionGreeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


# ===== 隐含波动率 (Newton-Raphson) =====


def implied_vol(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> Optional[float]:
    """
    用 Newton-Raphson 迭代法计算隐含波动率。

    Args:
        market_price: 市场价格 (mid price)
        S, K, T, r: BS 参数
        option_type: "call" 或 "put"
        tol: 收敛精度
        max_iter: 最大迭代次数

    Returns:
        隐含波动率 (None 如果无法收敛)
    """
    if market_price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None

    # 初始猜测
    sigma = 0.3  # 30% 初始值

    for _ in range(max_iter):
        price = bs_price(S, K, T, r, sigma, option_type)
        diff = price - market_price

        if abs(diff) < tol:
            return sigma

        # Vega (未除以 100 的版本，用于 Newton 步长)
        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
        vega_raw = S * norm.pdf(d1) * sqrt_T

        if vega_raw < 1e-12:
            break

        sigma = sigma - diff / vega_raw

        # 保持 sigma 在合理范围
        if sigma <= 0.001:
            sigma = 0.001
        if sigma > 10.0:
            sigma = 10.0

    # 检查是否收敛
    final_price = bs_price(S, K, T, r, sigma, option_type)
    if abs(final_price - market_price) < tol * 100:
        return sigma

    return None


# ===== IV Rank & IV Percentile =====


def iv_rank(current_iv: float, iv_history: List[float]) -> float:
    """
    IV Rank: 当前 IV 在历史 N 天的百分位。

    Formula: (current_iv - min_iv) / (max_iv - min_iv) * 100

    Args:
        current_iv: 当前隐含波动率
        iv_history: 历史 IV 列表 (至少 20 天)

    Returns:
        IV Rank (0-100)
    """
    if not iv_history or len(iv_history) < 2:
        return 50.0  # 默认中位

    min_iv = min(iv_history)
    max_iv = max(iv_history)

    if max_iv == min_iv:
        return 50.0

    rank = (current_iv - min_iv) / (max_iv - min_iv) * 100
    return max(0.0, min(100.0, rank))


def iv_percentile(current_iv: float, iv_history: List[float]) -> float:
    """
    IV Percentile: 历史 N 天中低于当前 IV 的天数占比。

    Args:
        current_iv: 当前隐含波动率
        iv_history: 历史 IV 列表

    Returns:
        IV Percentile (0-100)
    """
    if not iv_history:
        return 50.0

    below = sum(1 for iv in iv_history if iv < current_iv)
    return (below / len(iv_history)) * 100


# ===== 波动率微笑分析 =====


def vol_smile_analysis(options_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    分析波动率微笑曲线。

    Args:
        options_data: 期权链数据列表，每个元素包含:
            {strike, option_type, iv, volume, open_interest}

    Returns:
        {
            "smile": [{"strike": float, "call_iv": float, "put_iv": float, "avg_iv": float}],
            "atm_iv": float,
            "skew_25d": float,  # 25-delta skew = put_iv(25d) - call_iv(25d)
            "smile_width": float,  # OTM IV 与 ATM IV 的平均差
        }
    """
    if not options_data:
        return {"smile": [], "atm_iv": 0, "skew_25d": 0, "smile_width": 0}

    # 按 strike 分组
    strikes: Dict[float, Dict[str, float]] = {}
    for opt in options_data:
        strike = opt.get("strike", 0)
        iv = opt.get("iv", 0)
        opt_type = opt.get("option_type", "").lower()

        if strike not in strikes:
            strikes[strike] = {"call_iv": 0, "put_iv": 0, "count": 0}

        if opt_type == "call":
            strikes[strike]["call_iv"] = iv
        elif opt_type == "put":
            strikes[strike]["put_iv"] = iv
        strikes[strike]["count"] += 1

    # 构建微笑曲线
    smile = []
    for strike in sorted(strikes.keys()):
        data = strikes[strike]
        call_iv = data["call_iv"]
        put_iv = data["put_iv"]
        avg_iv = (call_iv + put_iv) / 2 if call_iv > 0 and put_iv > 0 else max(call_iv, put_iv)
        smile.append(
            {
                "strike": strike,
                "call_iv": round(call_iv * 100, 2),
                "put_iv": round(put_iv * 100, 2),
                "avg_iv": round(avg_iv * 100, 2),
            }
        )

    # ATM IV (中间 strike)
    if smile:
        mid_idx = len(smile) // 2
        atm_iv = smile[mid_idx]["avg_iv"]
    else:
        atm_iv = 0

    # Skew: OTM Put IV vs OTM Call IV (简化: 用最低和最高 strike)
    skew_25d = 0.0
    if len(smile) >= 3:
        otm_put_iv = smile[1]["put_iv"] if smile[1]["put_iv"] > 0 else smile[1]["avg_iv"]
        otm_call_iv = smile[-2]["call_iv"] if smile[-2]["call_iv"] > 0 else smile[-2]["avg_iv"]
        skew_25d = otm_put_iv - otm_call_iv

    # Smile width: OTM IV 与 ATM IV 的平均差
    smile_width = 0.0
    if len(smile) >= 3 and atm_iv > 0:
        otm_ivs = [s["avg_iv"] for s in smile if s != smile[mid_idx]]
        if otm_ivs:
            smile_width = sum(abs(iv - atm_iv) for iv in otm_ivs) / len(otm_ivs)

    return {
        "smile": smile,
        "atm_iv": round(atm_iv, 2),
        "skew_25d": round(skew_25d, 2),
        "smile_width": round(smile_width, 2),
    }


# ===== 批量计算期权 Greeks =====


def compute_option_chain_greeks(
    spot_price: float,
    risk_free_rate: float,
    options_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    批量计算期权链的 Greeks 和 IV。

    Args:
        spot_price: 标的现价
        risk_free_rate: 无风险利率
        options_data: 期权链原始数据，每个元素:
            {strike, expiry, option_type, bid, ask, volume, open_interest, days_to_expiry}

    Returns:
        附加了 greeks 和 iv 的期权数据列表
    """
    results = []

    for opt in options_data:
        strike = opt.get("strike", 0)
        expiry = opt.get("expiry", "")
        opt_type = opt.get("option_type", "call")
        bid = opt.get("bid", 0)
        ask = opt.get("ask", 0)
        volume = opt.get("volume", 0)
        oi = opt.get("open_interest", 0)
        dte = opt.get("days_to_expiry", 30)

        # 到期时间 (年)
        T = max(dte / 365.0, 1 / 365.0)

        # 中间价
        mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else max(bid, ask)

        # 计算 IV
        iv = None
        if mid_price > 0:
            iv = implied_vol(mid_price, spot_price, strike, T, risk_free_rate, opt_type)

        # 计算 Greeks (使用 IV 或默认 30%)
        sigma = iv if iv and iv > 0 else 0.30
        greeks = bs_greeks(spot_price, strike, T, risk_free_rate, sigma, opt_type)

        results.append(
            {
                "strike": strike,
                "expiry": expiry,
                "option_type": opt_type,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "mid": round(mid_price, 2),
                "volume": volume,
                "open_interest": oi,
                "days_to_expiry": dte,
                "iv": round(iv * 100, 2) if iv else None,
                "greeks": greeks.to_dict(),
                "moneyness": round(spot_price / strike, 4) if strike > 0 else 0,
            }
        )

    return results
