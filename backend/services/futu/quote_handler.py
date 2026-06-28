"""
Futu 行情数据处理模块
负责实时行情、历史K线、盘口深度等行情相关功能
"""

import asyncio
import time
from typing import Any, Dict

import pandas as pd
from futu import RET_OK, AuType, KLType, SubType

from backend.core.retry_utils import with_global_retry

from .cache_manager import CacheManager


class QuoteHandler:
    """行情数据处理器"""

    def __init__(self, connection_manager, cache_manager: CacheManager):
        self.conn_mgr = connection_manager
        self.cache_mgr = cache_manager

    @with_global_retry
    async def get_quote(
        self, ticker: str, format_ticker_func, is_unsupported_func
    ) -> Dict[str, Any]:  # noqa: E501
        """获取实时行情（带L1缓存）"""
        if is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker)

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_quote(market_ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # L1 极速内存缓存 (TTL: 3秒)
        now = time.time()
        cached = self.cache_mgr.get_quote_cache(market_ticker)
        if cached and now - cached[0] < 3.0:
            return cached[1]

        topic = (market_ticker, SubType.QUOTE)
        if topic not in self.cache_mgr.subscribed_topics:
            ret, msg = self.conn_mgr.quote_ctx.subscribe(
                [market_ticker],
                [SubType.QUOTE],
                subscribe_push=False,
                extended_time=True,  # noqa: E501
            )
            if ret != RET_OK:
                return {"status": "error", "message": msg}
            self.cache_mgr.subscribed_topics.add(topic)

        ret, df = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_stock_quote, [market_ticker]
        )
        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            return {"status": "error", "message": f"行情获取失败: {df}"}

        result = self.cache_mgr.compress_quote_data(df.iloc[0])
        self.cache_mgr.set_quote_cache(market_ticker, now, result)
        return result

    @with_global_retry
    async def get_history(
        self, ticker: str, ktype: str = "K_DAY", num: int = 60
    ) -> Dict[str, Any]:  # noqa: E501
        """获取历史K线数据（带缓存和降级策略）"""
        from .utils import format_ticker, is_futu_unsupported

        if is_futu_unsupported(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker(ticker)

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_history(market_ticker, num)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        cache_key = f"futu_history_{market_ticker}_{ktype}"
        now = time.time()
        cached = self.cache_mgr.get_history_cache(cache_key)
        if cached and now - cached[0] < 60.0:
            data = cached[1]
            # 如果缓存的数据量足够，直接切片返回
            if data.get("status") == "success" and "data" in data:
                if len(data["data"]) >= num:
                    return {
                        "status": "success",
                        "ticker": market_ticker,
                        "data": data["data"][-num:],
                    }  # noqa: E501
            else:
                return data

        kt = getattr(KLType, ktype.upper(), KLType.K_DAY)
        st = getattr(SubType, ktype.upper(), SubType.K_DAY)

        # 优化：优先使用 get_cur_kline (消耗订阅额度，比历史额度更宽松)
        topic = (market_ticker, st)
        if topic not in self.cache_mgr.subscribed_topics:
            sub_ret, _ = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.subscribe,
                [market_ticker],
                [st],
                subscribe_push=False,  # noqa: E501
            )
            if sub_ret == RET_OK:
                self.cache_mgr.subscribed_topics.add(topic)

        ret, df = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_cur_kline, market_ticker, num, kt, AuType.QFQ
        )

        if ret != RET_OK or not isinstance(df, pd.DataFrame) or df.empty:
            # 降级使用 request_history_kline
            ret, df, page_key = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.request_history_kline,
                market_ticker,
                start=None,
                end=None,
                ktype=kt,
                autype=AuType.QFQ,
                max_count=num,  # noqa: E501
            )

        if ret != RET_OK:
            res = {"status": "error", "message": f"历史K线获取失败: {df}"}
            self.cache_mgr.set_history_cache(cache_key, now, res)
            return res

        kl_list = []
        if isinstance(df, pd.DataFrame) and not df.empty:
            for _, row in df.iterrows():
                kl_list.append(
                    {
                        "time": str(row.get("time_key", "")),
                        "open": float(row.get("open", 0.0)),
                        "high": float(row.get("high", 0.0)),
                        "low": float(row.get("low", 0.0)),
                        "close": float(row.get("close", 0.0)),
                        "volume": float(row.get("volume", 0.0)),
                    }
                )

        res = {"status": "success", "ticker": market_ticker, "data": kl_list}
        self.cache_mgr.set_history_cache(cache_key, now, res)
        return res

    @with_global_retry
    async def unsubscribe_quote(
        self, ticker: str, format_ticker_func
    ) -> Dict[str, Any]:  # noqa: E501
        """退订个股行情，释放 OpenD 订阅额度槽位"""
        market_ticker = format_ticker_func(ticker)

        if not self.conn_mgr.quote_ctx or self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "message": "Futu OpenD 未连接"}

        try:

            def _do_unsub():
                # 退订高频占用槽位的行情推送类型 (包含基础报价、深度摆盘、逐笔成交、席位等)  # noqa: E501
                sub_types = [
                    SubType.QUOTE,
                    SubType.ORDER_BOOK,
                    SubType.TICKER,
                    SubType.BROKER,
                    SubType.K_DAY,
                ]  # noqa: E501
                ret, data = self.conn_mgr.quote_ctx.unsubscribe(
                    [market_ticker], sub_types
                )  # noqa: E501

                if ret == RET_OK:
                    # 同步清理内部的主题追踪缓存
                    for st in sub_types:
                        self.cache_mgr.subscribed_topics.discard((market_ticker, st))
                    return {"status": "success", "message": f"成功退订 {market_ticker}"}
                return {"status": "error", "message": str(data)}

            return await asyncio.to_thread(_do_unsub)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @with_global_retry
    async def get_order_book(
        self, ticker: str, format_ticker_func, is_unsupported_func
    ) -> Dict[str, Any]:  # noqa: E501
        """获取实时 Level 2 盘口深度数据"""
        if is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker)

        # 开发环境 Mock
        if (
            self.conn_mgr.status != "CONNECTED"
            and __import__("os").getenv("QUANT_ENV") == "development"
        ):  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_order_book(market_ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # L1 极速内存缓存 (TTL: 1秒)
        cache_key = f"futu_ob_{market_ticker}"
        now = time.time()
        cached = self.cache_mgr.get_order_book_cache(cache_key)
        if cached and now - cached[0] < 1.0:
            return cached[1]

        topic = (market_ticker, SubType.ORDER_BOOK)
        if topic not in self.cache_mgr.subscribed_topics:
            ret, msg = self.conn_mgr.quote_ctx.subscribe(
                [market_ticker], [SubType.ORDER_BOOK], subscribe_push=False
            )
            if ret != RET_OK:
                return {"status": "error", "message": f"盘口订阅失败: {msg}"}
            self.cache_mgr.subscribed_topics.add(topic)

        ret, data = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_order_book, market_ticker
        )
        if ret != RET_OK or not isinstance(data, dict):
            return {"status": "error", "message": f"盘口获取失败: {data}"}

        bids = [{"price": float(p), "size": int(v)} for p, v, *_ in data.get("Bid", [])]
        asks = [{"price": float(p), "size": int(v)} for p, v, *_ in data.get("Ask", [])]
        result = {
            "status": "success",
            "ticker": market_ticker,
            "bids": bids,
            "asks": asks,
        }  # noqa: E501
        self.cache_mgr.set_order_book_cache(cache_key, now, result)
        return result
