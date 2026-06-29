"""
Futu QuoteHandler 单元测试
覆盖: get_quote/get_history/unsubscribe_quote/get_order_book
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_OK

from backend.services.futu.cache_manager import CacheManager
from backend.services.futu.quote_handler import QuoteHandler


def _make_handler():
    """构造 QuoteHandler + 已连接的 mock conn_mgr"""
    conn_mgr = MagicMock()
    conn_mgr.status = "CONNECTED"
    conn_mgr.quote_ctx = MagicMock()
    cache_mgr = CacheManager()
    return QuoteHandler(conn_mgr, cache_mgr), conn_mgr, cache_mgr


def _fmt(t):
    return t.upper()


def _unsupported(t):
    """模拟 is_futu_unsupported：外汇/加密货币等"""
    t = t.upper()
    return "=" in t or "-" in t or "^" in t or t in ["DX-Y.NYB", "DGS10", "GC=F"]


class TestQuoteHandler:
    """QuoteHandler 行情处理器测试套件"""

    @pytest.mark.asyncio
    async def test_get_quote_unsupported_returns_error(self):
        """非支持资产（如外汇 GC=F）应直接返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_quote("GC=F", _fmt, _unsupported)
        assert result["status"] == "error"
        assert "不支持" in result["message"]

    @pytest.mark.asyncio
    async def test_get_quote_no_quote_ctx_returns_error(self):
        """未连接时（非 dev 环境）应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_quote("HK.00700", _fmt, _unsupported)
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_quote_dev_env_uses_mock_provider(self):
        """dev 环境未连接时应使用 MockProvider"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_quote("HK.00700", _fmt, _unsupported)
        assert result["status"] == "success"
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_quote_cache_hit_returns_cached(self):
        """L1 缓存命中时应直接返回缓存"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.set_quote_cache("HK.00700", time.time(), {"status": "success", "cached": True})
        result = await handler.get_quote("HK.00700", _fmt, _unsupported)
        assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_get_quote_subscribe_failure_returns_error(self):
        """subscribe 返回非 RET_OK 时应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (-1, "subscribe failed")
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, pd.DataFrame({"code": ["HK.00700"]})))):
            result = await handler.get_quote("HK.00700", _fmt, _unsupported)
        # subscribe 失败直接返回错误
        assert result["status"] == "error"
        assert "subscribe failed" in result["message"]

    @pytest.mark.asyncio
    async def test_get_quote_success_returns_compressed(self):
        """成功获取行情应返回压缩后的快照"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        df = pd.DataFrame(
            {"code": ["HK.00700"], "last_price": [350.0], "prev_close_price": [345.0], "volume": [1000000]}
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, df))):
            result = await handler.get_quote("HK.00700", _fmt, _unsupported)
        assert result["status"] == "success"
        assert result["ticker"] == "HK.00700"
        assert "change_pct" in result
        assert "volume_str" in result

    @pytest.mark.asyncio
    async def test_get_history_unsupported_returns_error(self):
        """get_history 不支持资产（如外汇）应返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_history("GC=F")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_history_dev_env_uses_mock(self):
        """dev 环境应使用 mock_history"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_history("HK.00700", num=5)
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_get_history_no_quote_ctx_returns_error(self):
        """未连接应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_history("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_history_cache_hit_returns_slice(self):
        """缓存命中且数量足够时应返回切片"""
        handler, _, cache_mgr = _make_handler()
        cache_key = "futu_history_HK.00700_K_DAY"
        data = [{"time": str(i), "open": i, "high": i, "low": i, "close": i, "volume": i} for i in range(100)]
        cache_mgr.set_history_cache(cache_key, time.time(), {"status": "success", "data": data})
        result = await handler.get_history("HK.00700", num=10)
        assert result["status"] == "success"
        assert len(result["data"]) == 10
        assert result["data"][-1]["close"] == 99

    @pytest.mark.asyncio
    async def test_get_history_cur_kline_success(self):
        """get_cur_kline 成功时应返回 K 线列表"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        df = pd.DataFrame(
            {
                "time_key": ["2026-01-01", "2026-01-02"],
                "open": [100.0, 110.0],
                "high": [105.0, 115.0],
                "low": [95.0, 105.0],
                "close": [102.0, 112.0],
                "volume": [1000, 2000],
            }
        )
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, df))):
            result = await handler.get_history("HK.00700", num=2)
        assert result["status"] == "success"
        assert len(result["data"]) == 2
        assert result["data"][0]["open"] == 100.0

    @pytest.mark.asyncio
    async def test_get_history_cur_kline_fail_falls_back_to_request_history(self):
        """get_cur_kline 失败时应降级到 request_history_kline"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        df = pd.DataFrame(
            {"time_key": ["2026-01-01"], "open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000]}
        )
        # 顺序：subscribe(2元) → get_cur_kline(2元) → request_history_kline(3元)
        call_results = [
            (RET_OK, ""),
            (-1, "cur_kline failed"),
            (RET_OK, df, "page_key"),
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return call_results.pop(0)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_history("HK.00700", num=1)
        assert result["status"] == "success"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_get_history_all_fail_returns_error(self):
        """所有数据源都失败时应返回错误并缓存错误状态"""
        handler, conn_mgr, cache_mgr = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        call_results = [
            (RET_OK, ""),
            (-1, "cur_kline failed"),
            (-1, "request_history failed", None),  # 3 元组匹配 request_history_kline 签名
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return call_results.pop(0)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_history("HK.00700", num=1)
        assert result["status"] == "error"
        cached = cache_mgr.get_history_cache("futu_history_HK.00700_K_DAY")
        assert cached is not None
        assert cached[1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_unsubscribe_quote_not_connected_returns_error(self):
        """未连接时 unsubscribe 应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        result = await handler.unsubscribe_quote("HK.00700", _fmt)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_unsubscribe_quote_success_clears_topics(self):
        """退订成功应清理 subscribed_topics 中相关主题"""
        handler, conn_mgr, cache_mgr = _make_handler()
        conn_mgr.quote_ctx.unsubscribe.return_value = (RET_OK, "")
        from futu import SubType

        cache_mgr.subscribed_topics.add(("HK.00700", SubType.QUOTE))
        cache_mgr.subscribed_topics.add(("HK.00700", SubType.ORDER_BOOK))

        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn())):
            result = await handler.unsubscribe_quote("HK.00700", _fmt)
        assert result["status"] == "success"
        assert ("HK.00700", SubType.QUOTE) not in cache_mgr.subscribed_topics
        assert ("HK.00700", SubType.ORDER_BOOK) not in cache_mgr.subscribed_topics

    @pytest.mark.asyncio
    async def test_unsubscribe_quote_failure_returns_error(self):
        """退订失败应返回错误信息"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.unsubscribe.return_value = (-1, "unsubscribe failed")
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda fn, *a, **kw: fn())):
            result = await handler.unsubscribe_quote("HK.00700", _fmt)
        assert result["status"] == "error"
        assert "unsubscribe failed" in result["message"]

    @pytest.mark.asyncio
    async def test_unsubscribe_quote_exception_returns_error(self):
        """退订过程中抛异常应返回 error 而非传播"""
        handler, conn_mgr, _ = _make_handler()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await handler.unsubscribe_quote("HK.00700", _fmt)
        assert result["status"] == "error"
        assert "boom" in result["message"]

    @pytest.mark.asyncio
    async def test_get_order_book_unsupported_returns_error(self):
        """order_book 不支持资产（外汇）应返回错误"""
        handler, _, _ = _make_handler()
        result = await handler.get_order_book("USDCNH=X", _fmt, _unsupported)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_order_book_dev_env_uses_mock(self):
        """dev 环境应使用 mock_order_book"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "development"}):
            result = await handler.get_order_book("HK.00700", _fmt, _unsupported)
        assert result["status"] == "success"
        assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_order_book_no_quote_ctx_returns_error(self):
        """未连接应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        conn_mgr.quote_ctx = None
        with patch.dict("os.environ", {"QUANT_ENV": "production"}):
            result = await handler.get_order_book("HK.00700", _fmt, _unsupported)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_order_book_cache_hit_returns_cached(self):
        """order_book L1 缓存（1s TTL）命中应返回缓存"""
        handler, _, cache_mgr = _make_handler()
        cache_mgr.set_order_book_cache("futu_ob_HK.00700", time.time(), {"status": "success", "cached": True})
        result = await handler.get_order_book("HK.00700", _fmt, _unsupported)
        assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_get_order_book_subscribe_failure_returns_error(self):
        """order_book subscribe 失败应返回错误"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (-1, "ob subscribe failed")
        result = await handler.get_order_book("HK.00700", _fmt, _unsupported)
        assert result["status"] == "error"
        assert "ob subscribe failed" in result["message"]

    @pytest.mark.asyncio
    async def test_get_order_book_success_returns_bids_asks(self):
        """成功获取盘口应返回 bids/asks 列表"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        ob_data = {
            "Bid": [(350.0, 1000, "B1"), (349.5, 500, "B2")],
            "Ask": [(350.5, 800, "A1"), (351.0, 600, "A2")],
        }
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(RET_OK, ob_data))):
            result = await handler.get_order_book("HK.00700", _fmt, _unsupported)
        assert result["status"] == "success"
        assert len(result["bids"]) == 2
        assert len(result["asks"]) == 2
        assert result["bids"][0]["price"] == 350.0
        assert result["bids"][0]["size"] == 1000
        assert result["asks"][0]["price"] == 350.5
