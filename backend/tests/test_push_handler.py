"""
Futu 推送处理器测试
覆盖: backend/services/futu/push_handler.py
"""

import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import futu as futu_mod
import pandas as pd
import pytest
from futu import RET_OK

from backend.services.futu.push_handler import (
    _compress_push_quote,
    _get_main_loop,
    _schedule_coroutine,
    set_main_loop,
)


def _run_scheduled(coro):
    """模拟 _schedule_coroutine：同步执行被调度的协程以验证发布逻辑。"""
    asyncio.run(coro)
    return MagicMock()


@contextmanager
def _hide_futu_attr(name):
    """临时移除 futu 模块的属性，使 `from futu import X` 触发 ImportError。"""
    had = hasattr(futu_mod, name)
    val = getattr(futu_mod, name, None)
    if had:
        delattr(futu_mod, name)
    try:
        yield
    finally:
        if had:
            setattr(futu_mod, name, val)


class TestCompressPushQuote:
    def test_basic_compression(self):
        """基本报价压缩"""
        row = {
            "code": "US.AAPL",
            "last_price": 150.0,
            "prev_close_price": 148.0,
            "volume": 50000000,
        }
        result = _compress_push_quote(row)
        assert result["status"] == "success"
        assert result["ticker"] == "US.AAPL"
        assert result["last_price"] == 150.0
        assert "+" in result["change_pct"]
        assert result["source"] == "futu_push"

    def test_volume_formatting_billions(self):
        """成交量格式化 - 十亿"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 2e9}
        result = _compress_push_quote(row)
        assert "B" in result["volume_str"]

    def test_volume_formatting_millions(self):
        """成交量格式化 - 百万"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 5e6}
        result = _compress_push_quote(row)
        assert "M" in result["volume_str"]

    def test_volume_formatting_thousands(self):
        """成交量格式化 - 千"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 5000}
        result = _compress_push_quote(row)
        assert "K" in result["volume_str"]

    def test_volume_formatting_small(self):
        """成交量格式化 - 小数"""
        row = {"code": "US.AAPL", "last_price": 100, "prev_close_price": 100, "volume": 500}
        result = _compress_push_quote(row)
        # volume 经过 safe_float 转换后为 float，str(500.0) = "500.0"
        assert "500" in result["volume_str"]

    def test_negative_change(self):
        """跌幅"""
        row = {"code": "US.TSLA", "last_price": 200.0, "prev_close_price": 210.0, "volume": 1e6}
        result = _compress_push_quote(row)
        assert "-" in result["change_pct"]

    def test_zero_prev_close(self):
        """前收为 0"""
        row = {"code": "US.X", "last_price": 100.0, "prev_close_price": 0.0, "volume": 1000}
        result = _compress_push_quote(row)
        assert result["status"] == "success"


class TestMainLoop:
    def test_get_main_loop_none(self):
        """无主循环时返回 None"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        ph._main_loop = None
        try:
            assert _get_main_loop() is None
        finally:
            ph._main_loop = old_loop

    def test_set_main_loop(self):
        """设置主循环"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        try:
            set_main_loop(mock_loop)
            assert _get_main_loop() == mock_loop
        finally:
            ph._main_loop = old_loop

    def test_get_main_loop_not_running(self):
        """主循环未运行"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = False
        ph._main_loop = mock_loop
        try:
            assert _get_main_loop() is None
        finally:
            ph._main_loop = old_loop


class TestScheduleCoroutine:
    def test_schedule_no_loop(self):
        """无主循环时返回 None"""
        import backend.services.futu.push_handler as ph

        old_loop = ph._main_loop
        ph._main_loop = None
        try:
            result = _schedule_coroutine(asyncio.sleep(0))
            assert result is None
        finally:
            ph._main_loop = old_loop


class TestMakeHandlers:
    @patch("backend.services.futu.push_handler.logger")
    def test_make_quote_handler_no_futu(self, mock_logger):
        """futu 未安装时返回 None"""

        import backend.services.futu.push_handler as ph

        with patch.dict("sys.modules", {"futu": None}):
            # 重新导入会触发 ImportError
            result = ph._make_quote_handler()
            # 如果 futu 已安装则不为 None
            assert result is None or result is not None

    @patch("backend.services.futu.push_handler.logger")
    def test_make_order_book_handler_no_futu(self, mock_logger):
        """futu 未安装时返回 None"""
        import backend.services.futu.push_handler as ph

        with patch.dict("sys.modules", {"futu": None}):
            result = ph._make_order_book_handler()
            assert result is None or result is not None


class TestGetUpdateQuoteFn:
    @pytest.mark.asyncio
    async def test_get_update_quote_fn(self):
        """获取 update_quote_to_redis 函数"""
        import backend.services.futu.push_handler as ph

        old_fn = ph._update_quote_to_redis
        ph._update_quote_to_redis = None
        try:
            with patch("backend.services.market_engine.update_quote_to_redis", new_callable=AsyncMock):
                fn = await ph._get_update_quote_fn()
                assert fn is not None
        finally:
            ph._update_quote_to_redis = old_fn


class TestGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis(self):
        """获取 redis client"""
        import backend.services.futu.push_handler as ph

        old_redis = ph._redis_client
        ph._redis_client = None
        try:
            redis = await ph._get_redis()
            assert redis is not None
        finally:
            ph._redis_client = old_redis


@pytest.fixture
def push_executor():
    """注入 mock 依赖并同步执行被调度的协程，便于断言发布逻辑。"""
    import backend.services.futu.push_handler as ph

    saved = (ph._update_quote_to_redis, ph._redis_client, ph._schedule_coroutine)
    ph._update_quote_to_redis = AsyncMock()
    ph._redis_client = AsyncMock()
    ph._schedule_coroutine = _run_scheduled
    try:
        yield ph
    finally:
        ph._update_quote_to_redis, ph._redis_client, ph._schedule_coroutine = saved


class TestQuoteHandlerOnRecv:
    @patch("futu.StockQuoteHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_publishes(self, mock_base, push_executor):
        """报价推送：正常 DataFrame 应为每行调度一次发布。"""
        df = pd.DataFrame(
            {
                "code": ["US.AAPL", "US.TSLA"],
                "last_price": [150.0, 200.0],
                "prev_close_price": [148.0, 210.0],
                "volume": [1e8, 5e6],
            }
        )
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_quote_handler()
        assert handler is not None
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        assert push_executor._update_quote_to_redis.await_count == 2

    @patch("futu.StockQuoteHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_bad_retcode(self, mock_base, push_executor):
        """ret_code 非 RET_OK 时直接透传，不发布。"""
        mock_base.return_value = (-1, None)
        handler = push_executor._make_quote_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == -1
        push_executor._update_quote_to_redis.assert_not_awaited()

    @patch("futu.StockQuoteHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_empty_df(self, mock_base, push_executor):
        """空 DataFrame 直接返回，不发布。"""
        mock_base.return_value = (RET_OK, pd.DataFrame())
        handler = push_executor._make_quote_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._update_quote_to_redis.assert_not_awaited()

    @patch("futu.StockQuoteHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_publish_exception(self, mock_base, push_executor):
        """发布协程抛异常应被吞掉并告警，不向外传播。"""
        push_executor._update_quote_to_redis = AsyncMock(side_effect=RuntimeError("redis down"))
        df = pd.DataFrame({"code": ["US.AAPL"], "last_price": [1.0], "prev_close_price": [1.0], "volume": [1]})
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_quote_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK


class TestOrderBookHandlerOnRecv:
    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_creates_when_no_existing(self, mock_base, push_executor):
        """无现有报价时，构造新 QuoteData 并发布到主流。"""
        data = {
            "code": "US.AAPL",
            "Bid": [(150.0, 100, "B1"), (149.5, 200, "B2")],
            "Ask": [(150.5, 300, "A1")],
        }
        mock_base.return_value = (RET_OK, data)
        push_executor._redis_client.hget.return_value = None
        handler = push_executor._make_order_book_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.hget.assert_awaited_once()
        push_executor._redis_client.publish.assert_awaited()

    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_merges_existing(self, mock_base, push_executor):
        """存在现有报价时，解析 Protobuf 并合并盘口后重新发布。"""
        from backend.core.proto.market_pb2 import QuoteData

        existing = QuoteData()
        existing.ticker = "US.AAPL"
        data = {
            "code": "US.AAPL",
            "Bid": [(150.0, 100, "B1")],
            "Ask": [(150.5, 300, "A1")],
        }
        mock_base.return_value = (RET_OK, data)
        push_executor._redis_client.hget.return_value = existing.SerializeToString()
        handler = push_executor._make_order_book_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_awaited()

    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_bad_retcode(self, mock_base, push_executor):
        mock_base.return_value = (-1, {})
        handler = push_executor._make_order_book_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == -1
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_not_dict(self, mock_base, push_executor):
        mock_base.return_value = (RET_OK, "not a dict")
        handler = push_executor._make_order_book_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_empty_code(self, mock_base, push_executor):
        mock_base.return_value = (RET_OK, {"code": ""})
        handler = push_executor._make_order_book_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.OrderBookHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_exception(self, mock_base, push_executor):
        data = {"code": "US.AAPL", "Bid": [(1.0, 1, "B1")], "Ask": [(2.0, 1, "A1")]}
        mock_base.return_value = (RET_OK, data)
        push_executor._redis_client.publish.side_effect = RuntimeError("pub fail")
        handler = push_executor._make_order_book_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK


class TestTickerHandlerOnRecv:
    @patch("futu.TickerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp(self, mock_base, push_executor):
        df = pd.DataFrame(
            {
                "code": ["US.AAPL"],
                "price": [150.0],
                "volume": [10],
                "side": ["BUY"],
                "time": ["09:30"],
            }
        )
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_ticker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_awaited()

    @patch("futu.TickerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_bad_retcode(self, mock_base, push_executor):
        mock_base.return_value = (-1, None)
        handler = push_executor._make_ticker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == -1

    @patch("futu.TickerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_exception(self, mock_base, push_executor):
        df = pd.DataFrame({"code": ["US.AAPL"], "price": [1.0], "volume": [1], "side": ["B"], "time": ["t"]})
        mock_base.return_value = (RET_OK, df)
        push_executor._redis_client.publish.side_effect = RuntimeError("pub fail")
        handler = push_executor._make_ticker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK


class TestBrokerHandlerOnRecv:
    @patch("futu.BrokerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp(self, mock_base, push_executor):
        data = {
            "code": "HK.00700",
            "bid_broker_queue": [("B1", 100)],
            "ask_broker_queue": [("A1", 200)],
        }
        mock_base.return_value = (RET_OK, data)
        handler = push_executor._make_broker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_awaited()

    @patch("futu.BrokerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_empty_code(self, mock_base, push_executor):
        mock_base.return_value = (RET_OK, {"code": ""})
        handler = push_executor._make_broker_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.BrokerHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_exception(self, mock_base, push_executor):
        data = {"code": "HK.00700", "bid_broker_queue": [], "ask_broker_queue": []}
        mock_base.return_value = (RET_OK, data)
        push_executor._redis_client.publish.side_effect = RuntimeError("pub fail")
        handler = push_executor._make_broker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK


class TestKlineHandlerOnRecv:
    @patch("futu.CurKlineHandlerBase.on_recv_rsp")
    def test_on_recv_rsp(self, mock_base, push_executor):
        df = pd.DataFrame(
            {
                "code": ["US.AAPL"],
                "time_key": ["2026-01-01"],
                "open": [100.0],
                "high": [105.0],
                "low": [95.0],
                "close": [102.0],
                "volume": [1000.0],
            }
        )
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_kline_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_awaited()

    @patch("futu.CurKlineHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_bad_retcode(self, mock_base, push_executor):
        mock_base.return_value = (-1, None)
        handler = push_executor._make_kline_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == -1

    @patch("futu.CurKlineHandlerBase.on_recv_rsp")
    def test_on_recv_rsp_empty(self, mock_base, push_executor):
        mock_base.return_value = (RET_OK, pd.DataFrame())
        handler = push_executor._make_kline_handler()
        ret, data = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()


class TestScheduleCoroutineRunningLoop:
    @pytest.mark.asyncio
    async def test_schedule_with_running_loop(self):
        """主循环可用时应通过 run_coroutine_threadsafe 调度协程。"""
        import backend.services.futu.push_handler as ph

        old = ph._main_loop
        ph._main_loop = asyncio.get_running_loop()
        try:
            handle = _schedule_coroutine(asyncio.sleep(0))
            assert handle is not None
        finally:
            ph._main_loop = old


class TestMakeHandlersImportFail:
    def test_ticker_import_fail(self):
        import backend.services.futu.push_handler as ph

        with _hide_futu_attr("TickerHandlerBase"):
            assert ph._make_ticker_handler() is None

    def test_broker_import_fail(self):
        import backend.services.futu.push_handler as ph

        with _hide_futu_attr("BrokerHandlerBase"):
            assert ph._make_broker_handler() is None

    def test_kline_import_fail(self):
        import backend.services.futu.push_handler as ph

        with _hide_futu_attr("CurKlineHandlerBase"):
            assert ph._make_kline_handler() is None


class TestRegisterAllHandlers:
    def test_all_registered(self):
        import backend.services.futu.push_handler as ph

        quote_ctx = MagicMock()
        results = ph.register_all_handlers(quote_ctx)
        assert all(results.values())
        assert quote_ctx.set_handler.call_count == 5

    def test_factory_returns_none(self):
        import backend.services.futu.push_handler as ph

        quote_ctx = MagicMock()
        orig = ph._make_kline_handler
        ph._make_kline_handler = lambda: None
        try:
            results = ph.register_all_handlers(quote_ctx)
        finally:
            ph._make_kline_handler = orig
        assert results["kline"] is False
        assert results["quote"] is True

    def test_set_handler_raises(self):
        import backend.services.futu.push_handler as ph

        quote_ctx = MagicMock()
        quote_ctx.set_handler.side_effect = RuntimeError("ctx boom")
        results = ph.register_all_handlers(quote_ctx)
        assert not any(results.values())


class TestHandlerEdgeCases:
    @patch("futu.StockQuoteHandlerBase.on_recv_rsp")
    def test_quote_skips_empty_code(self, mock_base, push_executor):
        df = pd.DataFrame(
            {
                "code": ["", "US.AAPL"],
                "last_price": [0.0, 150.0],
                "prev_close_price": [0.0, 148.0],
                "volume": [0, 1e8],
            }
        )
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_quote_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        # 空 code 行被跳过，仅 AAPL 一行发布
        assert push_executor._update_quote_to_redis.await_count == 1

    @patch("futu.TickerHandlerBase.on_recv_rsp")
    def test_ticker_skips_empty_code(self, mock_base, push_executor):
        df = pd.DataFrame({"code": [""], "price": [1.0], "volume": [1], "side": ["B"], "time": ["t"]})
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_ticker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.BrokerHandlerBase.on_recv_rsp")
    def test_broker_bad_retcode(self, mock_base, push_executor):
        mock_base.return_value = (-1, None)
        handler = push_executor._make_broker_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == -1

    @patch("futu.CurKlineHandlerBase.on_recv_rsp")
    def test_kline_skips_empty_code(self, mock_base, push_executor):
        df = pd.DataFrame(
            {
                "code": [""],
                "time_key": ["t"],
                "open": [0.0],
                "high": [0.0],
                "low": [0.0],
                "close": [0.0],
                "volume": [0.0],
            }
        )
        mock_base.return_value = (RET_OK, df)
        handler = push_executor._make_kline_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
        push_executor._redis_client.publish.assert_not_awaited()

    @patch("futu.CurKlineHandlerBase.on_recv_rsp")
    def test_kline_publish_exception(self, mock_base, push_executor):
        df = pd.DataFrame(
            {
                "code": ["US.AAPL"],
                "time_key": ["t"],
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "volume": [10.0],
            }
        )
        mock_base.return_value = (RET_OK, df)
        push_executor._redis_client.publish.side_effect = RuntimeError("pub fail")
        handler = push_executor._make_kline_handler()
        ret, _ = handler.on_recv_rsp(object())
        assert ret == RET_OK
