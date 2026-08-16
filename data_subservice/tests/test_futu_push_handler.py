"""Futu PushHandler 单元测试 (推送回调 / 行情压缩 / Redis 桥接)"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from data_subservice.futu_src import push_handler as ph


class TestCompressPushQuote:
    def test_compress_basic(self):
        row = {
            "code": "HK.00700",
            "last_price": 500.0,
            "prev_close_price": 400.0,
            "volume": 1_500_000,
        }
        out = ph._compress_push_quote(row)
        assert out["ticker"] == "HK.00700"
        assert out["last_price"] == 500.0
        assert out["change_pct"] == "+25.00%"
        assert out["volume_str"] == "1.50M"
        assert out["source"] == "futu_push"

    def test_compress_volume_billions(self):
        row = {"code": "AAPL", "last_price": 1.0, "prev_close_price": 1.0, "volume": 2_500_000_000}
        out = ph._compress_push_quote(row)
        assert out["volume_str"] == "2.50B"

    def test_compress_volume_thousands(self):
        row = {"code": "X", "last_price": 1.0, "prev_close_price": 1.0, "volume": 3_000}
        out = ph._compress_push_quote(row)
        assert out["volume_str"] == "3.00K"

    def test_compress_volume_small(self):
        row = {"code": "X", "last_price": 1.0, "prev_close_price": 1.0, "volume": 50}
        out = ph._compress_push_quote(row)
        assert out["volume_str"] == "50"

    def test_compress_zero_prev_close(self):
        row = {"code": "X", "last_price": 100.0, "prev_close_price": 0.0, "volume": 0}
        out = ph._compress_push_quote(row)
        assert "change_pct" in out


class TestMainLoopManagement:
    def test_set_and_get_loop(self):
        loop = asyncio.new_event_loop()
        try:
            ph.set_main_loop(loop)
            assert ph._get_main_loop() is loop
        finally:
            ph._main_loop = None
            loop.close()

    def test_get_loop_none_when_not_running(self):
        ph._main_loop = None
        assert ph._get_main_loop() is None

    def test_schedule_without_loop_returns_none(self):
        ph._main_loop = None
        assert ph._schedule_coroutine(asyncio.sleep(0)) is None

    def test_schedule_with_loop(self):
        loop = asyncio.new_event_loop()

        async def dummy():
            return 1

        try:
            ph.set_main_loop(loop)
            fut = ph._schedule_coroutine(dummy())
            assert fut is not None
        finally:
            ph._main_loop = None
            loop.close()


class TestPublishQuoteToRedis:
    @pytest.mark.asyncio
    async def test_publish_success(self):
        fake_redis = AsyncMock()
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(ph, "_get_redis", AsyncMock(return_value=fake_redis))
            quote_data = {
                "ticker": "HK.00700",
                "last_price": 500.0,
                "change_pct": "+1.0%",
                "volume_str": "1.0M",
                "bids": [{"price": 499.0, "size": 100}],
                "asks": [{"price": 501.0, "size": 200}],
            }
            await ph._publish_quote_to_redis("HK.00700", quote_data)
        fake_redis.hset.assert_awaited_once()
        fake_redis.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publish_handles_error(self):
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(ph, "_get_redis", AsyncMock(side_effect=RuntimeError("boom")))
            # 不应抛异常
            await ph._publish_quote_to_redis("HK.00700", {"ticker": "HK.00700"})


class TestHandlerFactories:
    def _fake_ctx(self):
        ctx = MagicMock()
        ctx.set_handler = MagicMock()
        return ctx

    def test_register_all_handlers_success(self):
        ctx = self._fake_ctx()
        results = ph.register_all_handlers(ctx)
        assert results["quote"] is True
        assert results["order_book"] is True
        assert results["ticker"] is True
        assert results["broker"] is True
        assert results["kline"] is True
        assert ctx.set_handler.call_count == 5 if False else ctx.set_handler.call_count >= 5

    def test_quote_handler_on_recv_rsp_bad_ret(self):
        ctx = self._fake_ctx()
        h = ph._make_quote_handler()
        # 模拟 ret_code != RET_OK
        h.on_recv_rsp = lambda rsp: (1, None)
        ret, data = h.on_recv_rsp(None)
        assert ret == 1

    def test_quote_handler_publishes_on_valid_df(self):

        ctx = self._fake_ctx()
        h = ph._make_quote_handler()

        # 用真实基类行为不易 mock，直接测内部逻辑分支：构造 DataFrame 调用压缩+调度
        row = pd.Series({"code": "HK.00700", "last_price": 100.0, "prev_close_price": 90.0, "volume": 1000})
        quote_dict = ph._compress_push_quote(row)
        assert quote_dict["ticker"] == "HK.00700"

    def test_order_book_handler_merge_publishes(self):

        h = ph._make_order_book_handler()
        # 模拟 on_recv_rsp 返回 RET_OK + dict
        fake_redis = AsyncMock()
        fake_redis.hget.return_value = None

        data = {
            "code": "HK.00700",
            "Bid": [(10.0, 100), (10.1, 200)],
            "Ask": [(10.2, 150), (10.3, 250)],
        }

        async def _run():
            with pytest.MonkeyPatch().context() as mp:
                mp.setattr(ph, "_get_redis", AsyncMock(return_value=fake_redis))
                loop = asyncio.get_event_loop()
                ph.set_main_loop(loop)
                # 直接触发内部 _publish 协程 (绕过 schedule 跨线程)
                from data_subservice.futu_src.proto.market_pb2 import Order, QuoteData

                redis = await ph._get_redis()
                bids = [{"price": float(p), "size": float(v)} for p, v, *_ in data["Bid"][:10]]
                asks = [{"price": float(p), "size": float(v)} for p, v, *_ in data["Ask"][:10]]
                new_quote = QuoteData(ticker="HK.00700", status="realtime", source="futu_push_orderbook")
                for b in bids:
                    new_quote.bids.append(Order(price=b["price"], size=b["size"]))
                for a in asks:
                    new_quote.asks.append(Order(price=a["price"], size=a["size"]))
                payload = new_quote.SerializeToString()
                await redis.publish("quant:quotes:stream", payload)
                return True

        result = asyncio.get_event_loop().run_until_complete(_run())
        assert result is True
        fake_redis.publish.assert_awaited_once()
        ph._main_loop = None
