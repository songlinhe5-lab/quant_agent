"""
Futu Mock 数据提供模块
为开发环境提供模拟数据
"""

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Tuple

from backend.services.options_engine import bs_greeks, bs_price


# 常见标的的演示现货价（其余回退到 150）
_SPOT_MAP = {
    "AAPL": 195.0,
    "TSLA": 250.0,
    "NVDA": 120.0,
    "MSFT": 420.0,
    "GOOGL": 175.0,
    "AMZN": 185.0,
    "META": 500.0,
    "BTC": 65000.0,
    "ETH": 3200.0,
}
_RISK_FREE = 0.045


def _spot_of(ticker: str) -> float:
    key = ticker.upper().replace("US.", "").replace("HK.", "").replace("CRYPTO.", "")
    return _SPOT_MAP.get(key, 150.0)


def _nice_step(raw: float) -> float:
    """取 1/2/5 ×10^n 的「好看」步长"""
    if raw <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(raw))
    norm = raw / mag
    if norm <= 1:
        step = 1.0
    elif norm <= 2:
        step = 2.0
    elif norm <= 5:
        step = 5.0
    else:
        step = 10.0
    return step * mag


def _strike_ladder(spot: float, n: int = 21) -> List[float]:
    step = _nice_step(spot * 0.025)
    atm = round(spot / step) * step
    half = n // 2
    return [round(atm + (i - half) * step, 2) for i in range(n)]


def _dte_of(expiration_date: str) -> Tuple[str, int]:
    today = date.today()
    if expiration_date:
        try:
            exp = datetime.strptime(expiration_date, "%Y-%m-%d").date()
            dte = max((exp - today).days, 1)
            return expiration_date, dte
        except ValueError:
            pass
    exp = today + timedelta(days=30)
    return exp.strftime("%Y-%m-%d"), 30


def _iv_smile(strike: float, spot: float, base: float, wing: float, skew: float) -> float:
    m = math.log(max(strike, 1e-6) / spot)
    smile = wing * abs(m)
    sk = skew * m if m < 0 else 0.0  # 虚值看跌（strike<spot）额外升水
    return max(0.02, base + smile + sk)


def _build_leg(
    ticker: str,
    spot: float,
    strike: float,
    dte: int,
    option_type: str,
    expiration_date: str,
) -> Dict[str, Any]:
    otype = "call" if option_type.upper() == "CALL" else "put"
    T = max(dte / 365.0, 1 / 365.0)
    if otype == "call":
        iv = _iv_smile(strike, spot, base=0.22, wing=0.12, skew=0.06)
    else:
        iv = _iv_smile(strike, spot, base=0.22, wing=0.12, skew=0.12)
    greeks = bs_greeks(spot, strike, T, _RISK_FREE, iv, otype)
    mid = bs_price(spot, strike, T, _RISK_FREE, iv, otype)
    spread = max(0.02, round(mid * 0.03, 2))
    bid = max(0.01, round(mid - spread / 2, 2))
    ask = round(mid + spread / 2, 2)
    if mid < 0.05:
        bid, ask = 0.01, 0.02
    m = math.log(max(strike, 1e-6) / spot)
    vol = int(5000 * math.exp(-3 * abs(m))) + 100
    oi = vol * 3
    code = f"US.{ticker.upper().replace('US.', '')}{expiration_date.replace('-', '')[2:]}{'C' if otype == 'call' else 'P'}{int(strike * 1000):08d}"
    return {
        "option_code": code,
        "option_type": option_type.upper(),
        "strike_price": strike,
        "implied_volatility": round(iv * 100, 2),
        "delta": greeks.delta,
        "gamma": greeks.gamma,
        "vega": greeks.vega,
        "theta": greeks.theta,
        "rho": greeks.rho,
        "bid": bid,
        "ask": ask,
        "volume": vol,
        "open_interest": oi,
        "days_to_expiry": dte,
        "expiration_date": expiration_date,
    }


class MockProvider:
    """Mock 数据提供者 - 用于开发环境"""

    @staticmethod
    def mock_quote(ticker: str) -> Dict[str, Any]:
        if len(ticker) > 10 and ("C0" in ticker or "P0" in ticker):
            return {
                "status": "success",
                "ticker": ticker,
                "last_price": 3.50,
                "change_pct": "+15.2%",
                "volume": 8500,
                "volume_str": "8.5K",
                "strike_price": 150.0,
                "implied_volatility": 0.35,
                "delta": 0.45,
                "source": "mock",
            }
        return {
            "status": "success",
            "ticker": ticker,
            "last_price": 150.0,
            "change_pct": "+1.2%",
            "volume": "1.2M",
            "source": "mock",
        }

    @staticmethod
    def mock_history(ticker: str, num: int) -> Dict[str, Any]:
        base = 150.0
        if "0700" in ticker:
            base = 370.0
        elif "BTC" in ticker:
            base = 65000.0

        kl_list = []
        for i in range(num):
            val = base + math.sin(i * 0.5) * (base * 0.02)
            kl_list.append(
                {
                    "time": f"2026-06-01 10:00:{i % 60:02d}",
                    "open": val * 0.99,
                    "high": val * 1.01,
                    "low": val * 0.98,
                    "close": val,
                    "volume": 1000,
                }
            )
        return {
            "status": "success",
            "ticker": ticker,
            "data": kl_list,
            "source": "mock",
        }  # noqa: E501

    @staticmethod
    def mock_option_chain(ticker: str, expiration_date: str) -> Dict[str, Any]:
        """生成含 IV 微笑 + Greeks + 买卖价 + 量仓 的丰富单到期日期权链（开发环境）。"""
        spot = _spot_of(ticker)
        date_str, dte = _dte_of(expiration_date)
        strikes = _strike_ladder(spot)
        calls = [_build_leg(ticker, spot, s, dte, "CALL", date_str) for s in strikes]
        puts = [_build_leg(ticker, spot, s, dte, "PUT", date_str) for s in strikes]
        return {
            "status": "success",
            "symbol": ticker,
            "underlying_price": spot,
            "expiration_date": date_str,
            "days_to_expiry": dte,
            "count": len(calls) + len(puts),
            # 兼容旧消费方（routers/options.py 读取 options）
            "options": calls + puts,
            "calls": calls,
            "puts": puts,
            "source": "mock",
        }

    @staticmethod
    def mock_option_chain_matrix(
        ticker: str, max_expiries: int = 8, max_strikes: int = 21
    ) -> Dict[str, Any]:
        """生成跨到期日的 IV 波动率曲面（开发环境），供前端热力图使用。"""
        spot = _spot_of(ticker)
        strikes = _strike_ladder(spot, max_strikes)
        today = date.today()
        dte_list = [7, 14, 21, 30, 45, 60, 90, 120, 180, 240]
        expirations = [
            (today + timedelta(days=d)).strftime("%Y-%m-%d")
            for d in dte_list[:max_expiries]
        ]

        legs: List[Dict[str, Any]] = []
        iv_call: List[List[float]] = []
        iv_put: List[List[float]] = []
        delta_call: List[List[float]] = []
        delta_put: List[List[float]] = []

        for exp, dte in zip(expirations, dte_list[:max_expiries]):
            T = max(dte / 365.0, 1 / 365.0)
            # 期限结构：越远月 base IV 略升
            base = 0.20 + 0.04 * (dte / 365.0)
            row_c_iv, row_p_iv, row_c_d, row_p_d = [], [], [], []
            for s in strikes:
                iv_c = _iv_smile(s, spot, base=base, wing=0.12, skew=0.06)
                iv_p = _iv_smile(s, spot, base=base, wing=0.12, skew=0.12)
                row_c_iv.append(round(iv_c * 100, 2))
                row_p_iv.append(round(iv_p * 100, 2))
                row_c_d.append(
                    round(bs_greeks(spot, s, T, _RISK_FREE, iv_c, "call").delta, 4)
                )
                row_p_d.append(
                    round(bs_greeks(spot, s, T, _RISK_FREE, iv_p, "put").delta, 4)
                )
                legs.append(
                    {
                        "type": "call",
                        "expiry": exp,
                        "strike": s,
                        "iv": round(iv_c * 100, 2),
                        "delta": row_c_d[-1],
                    }
                )
                legs.append(
                    {
                        "type": "put",
                        "expiry": exp,
                        "strike": s,
                        "iv": round(iv_p * 100, 2),
                        "delta": row_p_d[-1],
                    }
                )
            iv_call.append(row_c_iv)
            iv_put.append(row_p_iv)
            delta_call.append(row_c_d)
            delta_put.append(row_p_d)

        return {
            "status": "success",
            "symbol": ticker,
            "underlying_price": spot,
            "expirations": expirations,
            "days_to_expiry": dte_list[:max_expiries],
            "strikes": strikes,
            "calls": {"iv": iv_call, "delta": delta_call},
            "puts": {"iv": iv_put, "delta": delta_put},
            "legs": legs,
            "source": "mock",
        }

    @staticmethod
    def mock_fund_flow(ticker: str) -> Dict[str, Any]:
        is_hk = "HK" in ticker.upper()
        return {
            "status": "success",
            "ticker": ticker,
            "main_fund_net_inflow": 45000000.0,
            "main_fund_net_inflow_str": "4500.00万",
            "broker_queue": {
                "bid_brokers_queue_str": "摩根士丹利, 瑞银, 高盛",
                "ask_brokers_queue_str": "花旗, 汇丰, 中银",
            }
            if is_hk
            else None,
            "order_book_level_1": {
                "bid1": {"price": 315.2, "volume": 125000},
                "ask1": {"price": 315.4, "volume": 86000},
            }
            if is_hk
            else None,
            "source": "mock",
        }

    @staticmethod
    def mock_fundamental(ticker: str) -> Dict[str, Any]:
        return {
            "status": "success",
            "data": {
                "ticker": ticker,
                "company_name": "Mock Company Ltd.",
                "trailing_PE": 15.5,
                "price_to_book": 1.2,
                "market_cap": 50000000000.0,
                "dividend_yield": "2.5%",
            },
            "source": "mock",
        }

    @staticmethod
    def mock_order_book(ticker: str) -> Dict[str, Any]:
        base_price = 150.0
        if "0700" in ticker:
            base_price = 370.0

        bids = [{"price": round(base_price - i * 0.1, 2), "size": 1000 * (10 - i)} for i in range(10)]
        asks = [{"price": round(base_price + 0.1 + i * 0.1, 2), "size": 1000 * (10 - i)} for i in range(10)]

        return {
            "status": "success",
            "ticker": ticker,
            "bids": bids,
            "asks": asks,
            "source": "mock",
        }

    @staticmethod
    def mock_account_info(market: str, env_str: str) -> Dict[str, Any]:
        is_hk = market.upper() == "HK"
        return {
            "status": "success",
            "environment": env_str,
            "market": market.upper(),
            "total_assets": 1000000.0,
            "cash": 250000.0,
            "power": 250000.0,
            "market_val": 750000.0,
            "currency": "HKD" if is_hk else "USD",
            "positions": [
                {
                    "code": "HK.00700" if is_hk else "US.AAPL",
                    "stock_name": "腾讯控股" if is_hk else "苹果",
                    "position_side": "LONG",
                    "qty": 1000.0,
                    "can_sell_qty": 1000.0,
                    "cost_price": 300.0 if is_hk else 150.0,
                    "market_val": 400000.0 if is_hk else 180000.0,
                    "pl_val": 100000.0 if is_hk else 30000.0,
                    "pl_ratio": 33.33 if is_hk else 20.0,
                }
            ],
            "message": f"[Mock] 成功获取 {env_str} 账户信息与持仓列表。",
        }
