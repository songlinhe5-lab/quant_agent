"""
Futu Mock 数据提供模块
为开发环境提供模拟数据
"""
import math
from typing import Any, Dict


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
                "source": "mock"
            }
        return {
            "status": "success",
            "ticker": ticker,
            "last_price": 150.0,
            "change_pct": "+1.2%",
            "volume": "1.2M",
            "source": "mock"
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
            kl_list.append({
                "time": f"2026-06-01 10:00:{i%60:02d}",
                "open": val*0.99,
                "high": val*1.01,
                "low": val*0.98,
                "close": val,
                "volume": 1000
            })
        return {"status": "success", "ticker": ticker, "data": kl_list, "source": "mock"}  # noqa: E501

    @staticmethod
    def mock_option_chain(ticker: str, expiration_date: str) -> Dict[str, Any]:
        date_str = expiration_date if expiration_date else "2024-01-19"
        return {
            "status": "success",
            "expiration_date": date_str,
            "count": 2,
            "options": [
                {
                    "option_code": f"US.{ticker.upper().replace('US.','')}240119C00150000",  # noqa: E501
                    "option_type": "CALL",
                    "strike_price": 150.0
                },
                {
                    "option_code": f"US.{ticker.upper().replace('US.','')}240119P00150000",  # noqa: E501
                    "option_type": "PUT",
                    "strike_price": 150.0
                }
            ],
            "source": "mock"
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
                "ask_brokers_queue_str": "花旗, 汇丰, 中银"
            } if is_hk else None,
            "order_book_level_1": {
                "bid1": {"price": 315.2, "volume": 125000},
                "ask1": {"price": 315.4, "volume": 86000},
            } if is_hk else None,
            "source": "mock"
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
                "dividend_yield": "2.5%"
            },
            "source": "mock"
        }

    @staticmethod
    def mock_order_book(ticker: str) -> Dict[str, Any]:
        base_price = 150.0
        if "0700" in ticker:
            base_price = 370.0

        bids = [
            {"price": round(base_price - i * 0.1, 2), "size": 1000 * (10 - i)}
            for i in range(10)
        ]
        asks = [
            {"price": round(base_price + 0.1 + i * 0.1, 2), "size": 1000 * (10 - i)}
            for i in range(10)
        ]

        return {
            "status": "success",
            "ticker": ticker,
            "bids": bids,
            "asks": asks,
            "source": "mock"
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
                    "pl_ratio": 33.33 if is_hk else 20.0
                }
            ],
            "message": f"[Mock] 成功获取 {env_str} 账户信息与持仓列表。"
        }
