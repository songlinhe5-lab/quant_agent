"""
Futu 期权与资金流处理模块
负责期权链、资金流向、基本面数据等功能
"""

import asyncio
import time
from typing import Any, Dict

import pandas as pd
from futu import RET_OK, SortField, SubType, WarrantRequest

from backend.core.retry_utils import with_global_retry
from backend.core.utils import safe_float

from .cache_manager import CacheManager
from .quote_handler import _execute_unsubscriptions


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
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_option_chain(ticker, expiration_date)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        if not expiration_date:
            ret, raw_date_data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_expiration_date, market_ticker
            )
            if ret != RET_OK or not isinstance(raw_date_data, pd.DataFrame) or raw_date_data.empty:  # noqa: E501
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
        if ret != RET_OK or not isinstance(chain_data, pd.DataFrame) or chain_data.empty:  # noqa: E501
            return {"status": "error", "message": f"期权链获取失败: {chain_data}"}

        result = self.cache_mgr.compress_chain_data(chain_data, expiration_date)
        if result.get("status") == "success":
            self.cache_mgr.set_option_chain_cache(cache_key, time.time(), result)
        return result

    @with_global_retry
    async def get_fund_flow(self, ticker: str, format_ticker_func=None, is_unsupported_func=None) -> Dict[str, Any]:
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
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
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

            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_capital_distribution, market_ticker)

        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            if "频率太高" in str(data) or "frequency" in str(data).lower():
                print(f"🚨 [Futu] 资金流向触发限流熔断！接口将强制全局休眠 60 秒以释放压力 ({data})")  # noqa: E501
                self.cache_mgr.ff_circuit_breaker_until = time.time() + 60.0
                from .mock_provider import MockProvider

                res = MockProvider.mock_fund_flow(ticker)
                self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
                return res

            res = {"status": "error", "message": f"资金流向数据获取失败: {data}"}
            self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
            return res

        row = data.iloc[0]
        main_in = safe_float(row.get("capital_in_super", 0)) + safe_float(row.get("capital_in_big", 0))  # noqa: E501
        main_out = safe_float(row.get("capital_out_super", 0)) + safe_float(row.get("capital_out_big", 0))  # noqa: E501

        broker_data, order_book_data = None, None
        if market_ticker.startswith("HK."):
            # LRU 订阅池管理：检查并确保容量
            need_sub = []
            for st in [SubType.BROKER, SubType.ORDER_BOOK]:
                if not self.cache_mgr.has_topic(market_ticker, st):
                    need_sub.append(st)

            if need_sub:
                evicted = self.cache_mgr.ensure_capacity(needed=len(need_sub))
                await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

                sub_ret, sub_err = await asyncio.to_thread(
                    self.conn_mgr.quote_ctx.subscribe,
                    [market_ticker],
                    need_sub,
                    subscribe_push=True,  # 开启推送，盘口/经纪商变动实时推送  # noqa: E501
                )
                if sub_ret == RET_OK:
                    for st in need_sub:
                        self.cache_mgr.touch_topic(market_ticker, st)
            else:
                sub_ret = RET_OK  # 已订阅，跳过

            if sub_ret == RET_OK:
                for _ in range(3):
                    await asyncio.sleep(0.3)
                    res = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_broker_queue, market_ticker)
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

                ret_ob, ob_data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_order_book, market_ticker)
                if ret_ob == RET_OK and isinstance(ob_data, dict):
                    bids, asks = ob_data.get("Bid", []), ob_data.get("Ask", [])
                    bid1 = {"price": safe_float(bids[0][0]), "volume": int(bids[0][1])} if bids else None  # noqa: E501
                    ask1 = {"price": safe_float(asks[0][0]), "volume": int(asks[0][1])} if asks else None  # noqa: E501
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
    async def get_fundamental(self, ticker: str, format_ticker_func=None, is_unsupported_func=None) -> Dict[str, Any]:
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
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_fundamental(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_market_snapshot, [market_ticker])
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

    @with_global_retry
    async def get_warrant_chain(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取港股窝轮/牛熊证链数据（用于市场多空情绪分析）"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker

        # 仅港股支持窝轮
        if not market_ticker.startswith("HK."):
            return {"status": "error", "message": f"窝轮/牛熊证仅支持港股标的，当前: {ticker}"}

        cache_key = f"futu_warrant_chain_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_option_chain_cache(cache_key)
        if cached and now - cached[0] < 300.0:  # 5分钟缓存
            return cached[1]

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            return self._mock_warrant_chain(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 按成交额降序，拉取最活跃的窝轮/牛熊证
        req = WarrantRequest()
        req.sort_field = SortField.TURNOVER
        req.ascend = False
        req.num = 200

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_warrant, market_ticker, req)
        if ret != RET_OK:
            return {"status": "error", "message": f"窝轮数据获取失败: {data}"}

        warrant_df, last_page, all_count = data
        if not isinstance(warrant_df, pd.DataFrame) or warrant_df.empty:
            return {"status": "error", "message": f"{ticker} 无可用窝轮/牛熊证数据"}

        result = self._compress_warrant_data(warrant_df, ticker, all_count)
        self.cache_mgr.set_option_chain_cache(cache_key, time.time(), result)
        return result

    def _compress_warrant_data(self, df: pd.DataFrame, ticker: str, all_count: int) -> Dict[str, Any]:
        """将窝轮 DataFrame 压缩为结构化摘要 + 情绪统计"""
        warrants = []
        call_count, put_count, bull_count, bear_count = 0, 0, 0, 0
        call_turnover, put_turnover = 0.0, 0.0

        for _, row in df.iterrows():
            wrt_type = str(row.get("type", ""))
            turnover = safe_float(row.get("turnover", 0))

            # 统计多空分布
            if wrt_type == "CALL":
                call_count += 1
                call_turnover += turnover
            elif wrt_type == "PUT":
                put_count += 1
                put_turnover += turnover
            elif wrt_type == "BULL":
                bull_count += 1
            elif wrt_type == "BEAR":
                bear_count += 1

            warrants.append(
                {
                    "code": str(row.get("stock", "")),
                    "name": str(row.get("name", "")),
                    "type": wrt_type,
                    "issuer": str(row.get("issuer", "")),
                    "strike_price": safe_float(row.get("strike_price", 0)),
                    "cur_price": safe_float(row.get("cur_price", 0)),
                    "premium": safe_float(row.get("premium", 0)),
                    "leverage": safe_float(row.get("leverage", 0)),
                    "delta": safe_float(row.get("delta", 0)),
                    "implied_volatility": safe_float(row.get("implied_volatility", 0)),
                    "turnover": turnover,
                    "volume": int(safe_float(row.get("volume", 0))),
                    "maturity_time": str(row.get("maturity_time", "")),
                    "street_rate": safe_float(row.get("street_rate", 0)),
                    "recovery_price": safe_float(row.get("recovery_price", 0)),
                }
            )

        # 情绪摘要
        total_call_put = call_count + put_count
        call_ratio = round(call_count / total_call_put * 100, 1) if total_call_put > 0 else 50.0
        total_bull_bear = bull_count + bear_count
        bull_ratio = round(bull_count / total_bull_bear * 100, 1) if total_bull_bear > 0 else 50.0

        sentiment = (
            "偏多" if call_ratio > 60 and bull_ratio > 60 else "偏空" if call_ratio < 40 and bull_ratio < 40 else "中性"
        )

        return {
            "status": "success",
            "ticker": ticker,
            "total_count": all_count,
            "sentiment_summary": {
                "call_count": call_count,
                "put_count": put_count,
                "bull_count": bull_count,
                "bear_count": bear_count,
                "call_ratio_pct": call_ratio,
                "bull_ratio_pct": bull_ratio,
                "call_turnover": call_turnover,
                "put_turnover": put_turnover,
                "sentiment": sentiment,
            },
            "warrants": warrants[:50],  # 返回前50只最活跃的
        }

    @staticmethod
    def _mock_warrant_chain(ticker: str) -> Dict[str, Any]:
        """开发环境 Mock 窝轮数据"""
        return {
            "status": "success",
            "ticker": ticker,
            "total_count": 4,
            "sentiment_summary": {
                "call_count": 2,
                "put_count": 1,
                "bull_count": 1,
                "bear_count": 0,
                "call_ratio_pct": 66.7,
                "bull_ratio_pct": 100.0,
                "call_turnover": 5_000_000.0,
                "put_turnover": 2_000_000.0,
                "sentiment": "偏多",
            },
            "warrants": [
                {
                    "code": "HK.19001",
                    "name": "MOCK_CALL@EC2612",
                    "type": "CALL",
                    "issuer": "MB",
                    "strike_price": 40.0,
                    "cur_price": 0.15,
                    "premium": 12.5,
                    "leverage": 8.2,
                    "delta": 0.45,
                    "implied_volatility": 42.0,
                    "turnover": 3_000_000.0,
                    "volume": 20_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 15.0,
                    "recovery_price": 0,
                },
                {
                    "code": "HK.19002",
                    "name": "MOCK_PUT@EC2612",
                    "type": "PUT",
                    "issuer": "SG",
                    "strike_price": 35.0,
                    "cur_price": 0.08,
                    "premium": 8.3,
                    "leverage": 6.5,
                    "delta": -0.35,
                    "implied_volatility": 38.0,
                    "turnover": 2_000_000.0,
                    "volume": 15_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 8.0,
                    "recovery_price": 0,
                },
            ],
        }
