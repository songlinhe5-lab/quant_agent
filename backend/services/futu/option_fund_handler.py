"""
Futu 期权与资金流处理模块
负责期权链、资金流向、基本面数据等功能
"""

import asyncio
import time
from typing import Any, Dict

import pandas as pd
from futu import RET_OK, SubType

from backend.core.retry_utils import with_global_retry
from backend.core.utils import safe_float

from .cache_manager import CacheManager


class OptionFundHandler:
    """期权与资金流处理器"""

    def __init__(self, connection_manager, cache_manager: CacheManager):
        self.conn_mgr = connection_manager
        self.cache_mgr = cache_manager

    @with_global_retry
    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:  # noqa: E501
        """获取期权链数据"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_option_chain_{market_ticker}_{expiration_date}"
        now = time.time()

        cached = self.cache_mgr.get_option_chain_cache(cache_key)
        if cached and now - cached[0] < 3600.0:
            return cached[1]

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_option_chain(ticker, expiration_date)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        if not expiration_date:
            ret, raw_date_data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_expiration_date, market_ticker
            )
            if (
                ret != RET_OK
                or not isinstance(raw_date_data, pd.DataFrame)
                or raw_date_data.empty
            ):  # noqa: E501
                return {
                    "status": "error",
                    "message": f"无法获取到期日列表: {raw_date_data}",
                }  # noqa: E501
            expiration_date = str(raw_date_data["strike_time"].iloc[0]).split(" ")[0]

        ret, chain_data = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_option_chain,
            market_ticker,
            start=expiration_date,
            end=expiration_date,
        )
        if (
            ret != RET_OK
            or not isinstance(chain_data, pd.DataFrame)
            or chain_data.empty
        ):  # noqa: E501
            return {"status": "error", "message": f"期权链获取失败: {chain_data}"}

        result = self.cache_mgr.compress_chain_data(chain_data, expiration_date)
        if result.get("status") == "success":
            self.cache_mgr.set_option_chain_cache(cache_key, time.time(), result)
        return result

    @with_global_retry
    async def get_fund_flow(
        self, ticker: str, format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取资金流向数据（带熔断机制）"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_fund_flow_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_fund_flow_cache(cache_key)
        if cached and now - cached[0] < 60.0:
            return cached[1]

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_fund_flow(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 🚨 全局熔断拦截
        if time.time() < self.cache_mgr.ff_circuit_breaker_until:
            from .mock_provider import MockProvider

            return MockProvider.mock_fund_flow(ticker)

        if self.cache_mgr.ff_lock is None:
            self.cache_mgr.ff_lock = asyncio.Lock()

        async with self.cache_mgr.ff_lock:
            # 全局限流排队：严格控制资金流向请求间隔
            elapsed = time.time() - self.cache_mgr.last_ff_time
            if elapsed < 0.6:
                await asyncio.sleep(0.6 - elapsed)
            self.cache_mgr.last_ff_time = time.time()

            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_capital_distribution, market_ticker
            )

        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            if "频率太高" in str(data) or "frequency" in str(data).lower():
                print(
                    f"🚨 [Futu] 资金流向触发限流熔断！接口将强制全局休眠 60 秒以释放压力 ({data})"
                )  # noqa: E501
                self.cache_mgr.ff_circuit_breaker_until = time.time() + 60.0
                from .mock_provider import MockProvider

                res = MockProvider.mock_fund_flow(ticker)
                self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
                return res

            res = {"status": "error", "message": f"资金流向数据获取失败: {data}"}
            self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
            return res

        row = data.iloc[0]
        main_in = safe_float(row.get("capital_in_super", 0)) + safe_float(
            row.get("capital_in_big", 0)
        )  # noqa: E501
        main_out = safe_float(row.get("capital_out_super", 0)) + safe_float(
            row.get("capital_out_big", 0)
        )  # noqa: E501

        broker_data, order_book_data = None, None
        if market_ticker.startswith("HK."):
            sub_ret, sub_err = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.subscribe,
                [market_ticker],
                [SubType.BROKER, SubType.ORDER_BOOK],
                subscribe_push=False,  # noqa: E501
            )
            if sub_ret == RET_OK:
                for _ in range(3):
                    await asyncio.sleep(0.3)
                    res = await asyncio.to_thread(
                        self.conn_mgr.quote_ctx.get_broker_queue, market_ticker
                    )
                    bid_df, ask_df = (
                        (res[1], res[2])
                        if res and res[0] == RET_OK and len(res) > 2
                        else (pd.DataFrame(), pd.DataFrame())
                    )  # noqa: E501
                    if (isinstance(bid_df, pd.DataFrame) and not bid_df.empty) or (
                        isinstance(ask_df, pd.DataFrame) and not ask_df.empty
                    ):
                        break

                if (isinstance(bid_df, pd.DataFrame) and not bid_df.empty) or (
                    isinstance(ask_df, pd.DataFrame) and not ask_df.empty
                ):

                    def parse_brokers(df):
                        return (
                            df[df.columns[1]].dropna().unique().tolist()[:10]
                            if isinstance(df, pd.DataFrame) and not df.empty
                            else []
                        )  # noqa: E501

                    def fmt_q(q):
                        return ", ".join(map(str, q)) if q else "暂无"

                    bid_q, ask_q = parse_brokers(bid_df), parse_brokers(ask_df)
                    broker_data = {
                        "bid_brokers_queue_str": fmt_q(bid_q),
                        "ask_brokers_queue_str": fmt_q(ask_q),
                    }

                ret_ob, ob_data = await asyncio.to_thread(
                    self.conn_mgr.quote_ctx.get_order_book, market_ticker
                )
                if ret_ob == RET_OK and isinstance(ob_data, dict):
                    bids, asks = ob_data.get("Bid", []), ob_data.get("Ask", [])
                    bid1 = (
                        {"price": safe_float(bids[0][0]), "volume": int(bids[0][1])}
                        if bids
                        else None
                    )  # noqa: E501
                    ask1 = (
                        {"price": safe_float(asks[0][0]), "volume": int(asks[0][1])}
                        if asks
                        else None
                    )  # noqa: E501
                    order_book_data = {"bid1": bid1, "ask1": ask1}

        def _fmt_money(val: float) -> str:
            if abs(val) >= 1_0000_0000:
                return f"{val / 1_0000_0000:.2f}亿"  # noqa: E701
            if abs(val) >= 1_0000:
                return f"{val / 1_0000:.2f}万"  # noqa: E701
            return f"{val:.2f}"

        result = {
            "status": "success",
            "ticker": ticker,
            "main_fund_net_inflow": main_in - main_out,
            "main_fund_net_inflow_str": _fmt_money(main_in - main_out),
            "broker_queue": broker_data,
            "order_book_level_1": order_book_data,
        }
        self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), result)
        return result

    @with_global_retry
    async def get_fundamental(
        self, ticker: str, format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取基本面数据"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_fundamental_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_fundamental_cache(cache_key)
        if cached and now - cached[0] < 3600.0:
            return cached[1]

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_fundamental(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        ret, data = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_market_snapshot, [market_ticker]
        )
        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            res = {"status": "error", "message": f"基本面数据获取失败: {data}"}
            self.cache_mgr.set_fundamental_cache(cache_key, time.time(), res)
            return res

        row = data.iloc[0]

        result = {
            "status": "success",
            "data": {
                "ticker": ticker,
                "company_name": str(row.get("name", "")),
                "trailing_PE": safe_float(row.get("pe_ratio", 0.0))
                if safe_float(row.get("pe_ratio", 0.0)) > 0
                else None,  # noqa: E501
                "price_to_book": safe_float(row.get("pb_rate", 0.0))
                if safe_float(row.get("pb_rate", 0.0)) > 0
                else None,  # noqa: E501
                "dividend_yield": f"{safe_float(row.get('dividend_yield', 0.0))}%"
                if safe_float(row.get("dividend_yield", 0.0)) > 0
                else None,  # noqa: E501
                "market_cap": safe_float(row.get("market_val", 0.0))
                if safe_float(row.get("market_val", 0.0)) > 0
                else None,  # noqa: E501
            },
        }
        result["data"] = {k: v for k, v in result["data"].items() if v is not None}
        self.cache_mgr.set_fundamental_cache(cache_key, time.time(), result)
        return result
