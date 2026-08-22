"""
Futu QuoteHandler 单元测试
覆盖: get_quote/get_history/unsubscribe_quote/get_order_book
      get_search_news/get_fed_watch_target_rate/get_heat_map_data/subscribe_quote
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from futu import RET_ERROR, RET_OK

from data_subservice.futu_src.cache_manager import CacheManager
from data_subservice.futu_src.quote_handler import QuoteHandler


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
            {
                "time_key": ["2026-01-01"],
                "open": [100.0],
                "high": [105.0],
                "low": [95.0],
                "close": [102.0],
                "volume": [1000],
            }
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
    async def test_get_history_request_history_pagination(self):
        """大跨度 num>370 时直接走 request_history_kline 分页, 拼接多页数据并去重排序"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")

        # 模拟 2 页: 第一页(较新) + 第二页(更早), 分页返回 page_req_key 直到 None
        def _make_page(days):
            return pd.DataFrame(
                {
                    "time_key": [f"2020-01-{d:02d}" for d in days],
                    "open": [100.0] * len(days),
                    "high": [105.0] * len(days),
                    "low": [95.0] * len(days),
                    "close": [102.0] * len(days),
                    "volume": [1000] * len(days),
                }
            )

        page1 = _make_page([5, 6])  # 较新
        page2 = _make_page([1, 2, 3])  # 更早
        page3 = _make_page([])  # 空页表示没有更多(模拟 page_key=None 后返回空)

        call_results = [
            (RET_OK, page1, "page2"),  # 首页
            (RET_OK, page2, "page3"),  # 第二页
            (RET_OK, page3, None),  # 最后一页 page_key=None
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return call_results.pop(0)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_history("HK.00700", num=400)
        assert result["status"] == "success"
        # 3+2=5 根去重后应全部返回(400 根数据量达不到, 按实际返回)
        times = [k["time"] for k in result["data"]]
        # 升序排列且去重
        assert times == sorted(times)
        assert len(times) == 5
        assert times[0] == "2020-01-01"

    @pytest.mark.asyncio
    async def test_get_history_pagination_keeps_recent_n(self):
        """分页拼接超过 num 根时, 应保留最近的 num 根(而非最旧), 保证视图能看到近期数据"""
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.subscribe.return_value = (RET_OK, "")
        # 两页共 5 根, num=2 时取最近 2 根(升序后取末尾)
        page1 = pd.DataFrame(
            {
                "time_key": ["2020-01-05", "2020-01-06", "2020-01-07"],
                "open": [1.0] * 3,
                "high": [2.0] * 3,
                "low": [0.5] * 3,
                "close": [1.5] * 3,
                "volume": [10] * 3,
            }
        )
        page2 = pd.DataFrame(
            {
                "time_key": ["2020-01-01", "2020-01-02"],
                "open": [1.0] * 2,
                "high": [2.0] * 2,
                "low": [0.5] * 2,
                "close": [1.5] * 2,
                "volume": [10] * 2,
            }
        )
        # mock has_topic=True 跳过 subscribe 步骤; get_cur_kline 失败强制进入分页
        handler.cache_mgr.has_topic = MagicMock(return_value=True)
        call_results = [
            (-1, "cur_kline failed"),
            (RET_OK, page1, "p2"),  # 首页较新
            (RET_OK, page2, None),  # 第二页更早, page_key=None 结束
        ]

        async def fake_to_thread(fn, *args, **kwargs):
            return call_results.pop(0)

        with patch("asyncio.to_thread", new=fake_to_thread):
            result = await handler.get_history("HK.00700", num=2)
        assert result["status"] == "success"
        times = [k["time"] for k in result["data"]]
        # 应保留最近的 2 根 (1/6, 1/7), 而非最旧 (1/1, 1/2)
        assert times == ["2020-01-06", "2020-01-07"]

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

        cache_mgr.touch_topic("HK.00700", SubType.QUOTE)
        cache_mgr.touch_topic("HK.00700", SubType.ORDER_BOOK)

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


class TestQuoteHandlerNewsFedHeat:
    """get_search_news / get_fed_watch_target_rate / get_heat_map_data 分支覆盖"""

    # ── get_search_news ──────────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_get_search_news_not_connected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_search_news("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_search_news_invalid_ticker(self):
        handler, _, _ = _make_handler()
        result = await handler.get_search_news("")
        assert result["status"] == "error"
        assert "无效" in result["message"]

    @pytest.mark.asyncio
    async def test_get_search_news_success_with_filter(self):
        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame(
            [
                {
                    "title": "A",
                    "news_sub_type": "NEWS",
                    "source": "x",
                    "publish_time": "t",
                    "url": "u",
                    "related_securities": ["HK.00772"],
                },
                {
                    "title": "B",
                    "news_sub_type": "NEWS",
                    "source": "x",
                    "publish_time": "t",
                    "url": "u",
                    "related_securities": ["HK.09988"],
                },
                {
                    "title": "C",
                    "news_sub_type": "NEWS",
                    "source": "x",
                    "publish_time": "t",
                    "url": "u",
                    "related_securities": [],
                },
            ]
        )
        conn_mgr.quote_ctx.get_search_news.return_value = (RET_OK, df)
        result = await handler.get_search_news("HK.00772")
        assert result["status"] == "success"
        # 仅保留关联 HK.00772 的（A），以及无关联标的的（C）
        assert result["count"] == 2
        headlines = {n["headline"] for n in result["data"]}
        assert headlines == {"A", "C"}

    @pytest.mark.asyncio
    async def test_get_search_news_unrelated_filtered_out(self):
        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame(
            [
                {
                    "title": "X",
                    "news_sub_type": "NEWS",
                    "source": "x",
                    "publish_time": "t",
                    "url": "u",
                    "related_securities": ["HK.09988"],
                },
            ]
        )
        conn_mgr.quote_ctx.get_search_news.return_value = (RET_OK, df)
        result = await handler.get_search_news("HK.00772")
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_get_search_news_empty_df(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_search_news.return_value = (RET_OK, pd.DataFrame())
        result = await handler.get_search_news("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_search_news_non_df(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_search_news.return_value = (-1, "fail")
        result = await handler.get_search_news("HK.00700")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_search_news_exception(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_search_news.side_effect = RuntimeError("boom")
        result = await handler.get_search_news("HK.00700")
        assert result["status"] == "error"
        assert "boom" in result["message"]

    # ── get_fed_watch_target_rate ───────────────────────────────────
    @pytest.mark.asyncio
    async def test_fed_watch_not_connected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_fed_watch_target_rate()
        assert result["status"] == "error"
        assert result["source"] == "futu"

    @pytest.mark.asyncio
    async def test_fed_watch_reconnecting(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        result = await handler.get_fed_watch_target_rate()
        assert result["status"] == "error"
        assert "重连" in result["message"]

    @pytest.mark.asyncio
    async def test_fed_watch_success(self):
        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame([{"rate": 4.5, "prob": 0.6}, {"rate": 4.75, "prob": 0.3}])
        conn_mgr.quote_ctx.get_fed_watch_target_rate.return_value = (RET_OK, df)
        result = await handler.get_fed_watch_target_rate()
        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["data"][0]["rate"] == 4.5

    @pytest.mark.asyncio
    async def test_fed_watch_bad_return(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_fed_watch_target_rate.return_value = (-1, "fail")
        result = await handler.get_fed_watch_target_rate()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_fed_watch_exception(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_fed_watch_target_rate.side_effect = RuntimeError("kaboom")
        result = await handler.get_fed_watch_target_rate()
        assert result["status"] == "error"
        assert "kaboom" in result["message"]

    # ── get_fed_watch_dot_plot（P1.8）───────────────────────────────
    @pytest.mark.asyncio
    async def test_fed_watch_dot_plot_success(self):
        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame(
            [
                {
                    "year": 2026,
                    "rate": 3.375,
                    "vote_count": 1,
                    "is_median": False,
                    "median_rate": 3.875,
                    "current_rate": 3.63,
                }
            ]
        )
        conn_mgr.quote_ctx.get_fed_watch_dot_plot.return_value = (RET_OK, df)
        result = await handler.get_fed_watch_dot_plot()
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["data"][0]["year"] == 2026

    @pytest.mark.asyncio
    async def test_fed_watch_dot_plot_fail(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_fed_watch_dot_plot.return_value = (-1, "fail")
        result = await handler.get_fed_watch_dot_plot()
        assert result["status"] == "error"

    # ── get_search_quote（P1.2 行情搜索）────────────────────────────
    @pytest.mark.asyncio
    async def test_search_quote_empty_keyword(self):
        handler, _, _ = _make_handler()
        result = await handler.get_search_quote("")
        assert result["status"] == "error"
        assert "空" in result["message"]

    @pytest.mark.asyncio
    async def test_search_quote_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_search_quote.return_value = (
            RET_OK,
            pd.DataFrame(
                [{"market": "HK", "code": "HK.00700", "name": "腾讯控股", "sec_type": "STOCK", "is_watched": True}]
            ),
        )
        result = await handler.get_search_quote("腾讯", 5)
        assert result["status"] == "success"
        assert result["count"] == 1
        assert result["data"][0]["code"] == "HK.00700"
        assert result["data"][0]["name"] == "腾讯控股"

    @pytest.mark.asyncio
    async def test_search_quote_cache_hit(self):
        handler, conn_mgr, cache_mgr = _make_handler()
        cache_mgr.set_search_quote_cache(
            "futu_search_quote_腾讯_5", time.time(), {"status": "success", "count": 1, "data": [{"code": "HK.00700"}]}
        )
        called = {"n": 0}

        def fake_get_search_quote(*args, **kw):
            called["n"] += 1
            return (RET_OK, pd.DataFrame())

        conn_mgr.quote_ctx.get_search_quote.side_effect = fake_get_search_quote
        result = await handler.get_search_quote("腾讯", 5)
        assert result["status"] == "success"
        assert called["n"] == 0, "缓存命中不应调 SDK"

    @pytest.mark.asyncio
    async def test_search_quote_fail(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_search_quote.return_value = (-1, "fail")
        result = await handler.get_search_quote("腾讯")
        assert result["status"] == "error"

    # ── get_heat_map_data ───────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_heat_map_not_connected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_heat_map_data("HK")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_heat_map_reconnecting(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.status = "DISCONNECTED"
        result = await handler.get_heat_map_data("HK")
        assert result["status"] == "error"
        assert "重连" in result["message"]

    @pytest.mark.asyncio
    async def test_heat_map_bad_shape(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_heat_map_data.return_value = {"wrong": 1}
        result = await handler.get_heat_map_data("HK")
        assert result["status"] == "error"
        assert "形态异常" in result["message"]

    @pytest.mark.asyncio
    async def test_heat_map_success(self):
        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame([{"code": "HK.00700", "change_rate": 1.2}, {"code": "HK.09988", "change_rate": -0.5}])
        conn_mgr.quote_ctx.get_heat_map_data.return_value = (RET_OK, df)
        result = await handler.get_heat_map_data("HK")
        assert result["status"] == "success"
        assert result["count"] == 2
        assert result["market"] == "HK"

    @pytest.mark.asyncio
    async def test_heat_map_bad_return(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_heat_map_data.return_value = (-1, "fail")
        result = await handler.get_heat_map_data("US")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_heat_map_a_share_maps_to_sh_market(self):
        """前端传 'A' 表示沪深A股, 必须映射到 futu Market.SH 而非 fallback HK。

        回归: 此前 getattr(Market, 'A', Market.HK) 匹配不到 → fallback 到港股,
        A 股热力图拿到港股数据甚至为空。
        """
        from futu import Market

        handler, conn_mgr, _ = _make_handler()
        df = pd.DataFrame([{"plate_name": "半导体", "change_rate": 0.8}])
        conn_mgr.quote_ctx.get_heat_map_data.return_value = (RET_OK, df)

        result = await handler.get_heat_map_data("A")

        assert result["status"] == "success"
        assert result["market"] == "SH"
        # 应把 Market.SH 传给 futu 接口 (而非 Market.HK), 并带 count/plate_type
        args, kwargs = conn_mgr.quote_ctx.get_heat_map_data.call_args
        assert args[0] == Market.SH
        assert kwargs.get("count") == 100

    @pytest.mark.asyncio
    async def test_map_heat_market_a_to_sh(self):
        """_map_heat_market: 'A'/'CN' → Market.SH, 其他市场正常映射。"""
        from futu import Market

        from data_subservice.futu_src.quote_handler import _map_heat_market

        assert _map_heat_market("A") == Market.SH
        assert _map_heat_market("CN") == Market.SH
        assert _map_heat_market("HK") == Market.HK
        assert _map_heat_market("US") == Market.US
        assert _map_heat_market("SZ") == Market.SZ
        # 未知市场 fallback HK
        assert _map_heat_market("XX") == Market.HK

    @pytest.mark.asyncio
    async def test_heat_map_exception(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_heat_map_data.side_effect = RuntimeError("boom")
        result = await handler.get_heat_map_data("HK")
        assert result["status"] == "error"
        assert "boom" in result["message"]

    # ── get_hk_sector_flow ──────────────────────────────────────────
    @pytest.mark.asyncio
    async def test_hk_sector_flow_not_connected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_hk_sector_flow()
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_hk_sector_flow_success(self):
        handler, conn_mgr, cache_mgr = _make_handler()
        plate_df = pd.DataFrame(
            [{"code": "HK.BK001", "plate_name": "金融"}, {"code": "HK.BK002", "plate_name": "科技"}]
        )
        stock_df = pd.DataFrame([{"code": "HK.00700", "turnover": 100}, {"code": "HK.09988", "turnover": 80}])
        cap_df = pd.DataFrame(
            [{"capital_in_super": 500.0, "capital_in_big": 200.0, "capital_out_super": 100.0, "capital_out_big": 50.0}]
        )
        conn_mgr.quote_ctx.get_plate_list.return_value = (RET_OK, plate_df)
        conn_mgr.quote_ctx.get_plate_stock.return_value = (RET_OK, stock_df)
        conn_mgr.quote_ctx.get_capital_distribution.return_value = (RET_OK, cap_df)
        result = await handler.get_hk_sector_flow()
        assert result["status"] == "success"
        assert len(result["data"]["sectors"]) == 2
        # 每板块聚合 2 只龙头，每只净流入 = (500+200) - (100+50) = 550 → 板块合计 1100
        assert result["data"]["sectors"][0]["net_inflow"] == 1100.0
        assert result["data"]["sectors"][0]["name"] == "金融"
        assert result["data"]["sectors"][0]["stock_count"] == 2

    @pytest.mark.asyncio
    async def test_hk_sector_flow_empty_plate_degraded(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_plate_list.return_value = (RET_OK, pd.DataFrame())
        result = await handler.get_hk_sector_flow()
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_hk_sector_flow_no_valid_flow_degraded(self):
        handler, conn_mgr, _ = _make_handler()
        plate_df = pd.DataFrame([{"code": "HK.BK001", "plate_name": "金融"}])
        stock_df = pd.DataFrame([{"code": "HK.00700", "turnover": 100}])
        conn_mgr.quote_ctx.get_plate_list.return_value = (RET_OK, plate_df)
        conn_mgr.quote_ctx.get_plate_stock.return_value = (RET_OK, stock_df)
        # 资金流接口失败 → 无有效聚合 → degraded
        conn_mgr.quote_ctx.get_capital_distribution.return_value = (RET_ERROR, "fail")
        result = await handler.get_hk_sector_flow()
        assert result["status"] == "degraded"
        assert result["data"]["sectors"] == []


# ── P2.2 机构持仓 / ARK 交易（美股聪明钱）──────────────────────────────
class TestInstitutionArk:
    """P2.2 机构/ARK 接口族"""

    async def test_institution_list_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_list.return_value = (
            RET_OK,
            pd.DataFrame(
                [
                    {
                        "institution_id": 1951572549,
                        "institution_name": "Vanguard",
                        "position_value": 5640083126208.48,
                        "position_count": 4358,
                    }
                ]
            ),
            "4",
            16806,
        )
        result = await handler.get_institution_list("US", 1, 1)
        assert result["status"] == "success"
        assert result["data"][0]["institution_id"] == 1951572549

    async def test_institution_holding_list_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_holding_list.return_value = (
            RET_OK,
            pd.DataFrame(
                [
                    {
                        "security": "US.AAPL",
                        "name": "苹果",
                        "holding_pct": 7.1438,
                        "change_shares": 4539754,
                        "holding_date": "2026-06-29",
                    }
                ]
            ),
            "4",
            4346,
        )
        result = await handler.get_institution_holding_list(1951572549, "US", None, 3, 1)
        assert result["status"] == "success"
        assert result["data"][0]["holding_pct"] == 7.1438

    async def test_institution_holding_change_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_holding_change.return_value = (
            RET_OK,
            pd.DataFrame([{"security": "US.VGNT", "name": "VERSIGENT", "change_pct": 5.2047}]),
            "4",
            2870,
        )
        result = await handler.get_institution_holding_change(1951572549, "US", None, 3, 1)
        assert result["status"] == "success"
        assert result["data"][0]["change_pct"] == 5.2047

    async def test_institution_distribution_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_distribution.return_value = (
            RET_OK,
            pd.DataFrame([{"industry_name": "电子", "position_value": 984326797686.31, "portfolio_pct": 18.13}]),
        )
        result = await handler.get_institution_distribution(1951572549, "US")
        assert result["status"] == "success"
        assert result["data"][0]["portfolio_pct"] == 18.13

    async def test_institution_profile_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_profile.return_value = (
            RET_OK,
            {
                "institution_name": "Vanguard",
                "new_count": 115,
                "sold_out_count": 24,
                "increase_count": 2878,
                "top10_pct": 20.5,
                "disclosure_date": "2026-08-13",
            },
        )
        result = await handler.get_institution_profile(1951572549, "US")
        assert result["status"] == "success"
        assert result["data"]["new_count"] == 115

    async def test_ark_fund_holding_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_ark_fund_holding.return_value = (
            RET_OK,
            pd.DataFrame(
                [
                    {
                        "security": "US.ACHR",
                        "name": "Archer",
                        "shares": 27642593,
                        "market_value": 168343391.37,
                        "weight": 1.22,
                    }
                ]
            ),
            "4",
            3,
        )
        result = await handler.get_ark_fund_holding("POSITION", "ONE_DAY", 3, 1)
        assert result["status"] == "success"
        assert result["data"][0]["weight"] == 1.22

    async def test_ark_active_transaction_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_ark_active_transaction.return_value = (
            RET_OK,
            pd.DataFrame([{"security": "US.BWXT", "name": "BWX", "change_amount": 11629809.0, "change_shares": 69979}]),
            "4",
            3,
        )
        result = await handler.get_ark_active_transaction("INCREASE", "ONE_DAY", 3, 1)
        assert result["status"] == "success"
        assert result["data"][0]["change_amount"] == 11629809.0

    async def test_p22_disconnected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None  # ctx 空 → handler 返回"未连接"
        result = await handler.get_institution_list("US", 1, 1)
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    async def test_institution_failure(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_institution_list.return_value = (-1, "no permission")
        result = await handler.get_institution_list("US", 1, 1)
        assert result["status"] == "error"


# ── G8 数据正确性基座（复权/交易日/额度/市场状态）────────────────────────
class TestG8DataCorrectness:
    """G8 复权因子 / 交易日历 / K线额度 / 市场状态"""

    async def test_rehab_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_rehab.return_value = (
            RET_OK,
            pd.DataFrame(
                [{"ex_div_date": "2005-04-19", "per_cash_div": 0.07, "forward_adj_factorA": 1.0, "split_ratio": None}]
            ),
        )
        result = await handler.get_rehab("HK.00700")
        assert result["status"] == "success"
        assert result["data"][0]["per_cash_div"] == 0.07
        assert result["data"][0]["split_ratio"] is None  # nan → None

    async def test_rehab_unsupported(self):
        handler, conn_mgr, _ = _make_handler()
        result = await handler.get_rehab(
            "GC=F", is_unsupported_func=lambda t: t.startswith("GC"), format_ticker_func=lambda t: t
        )
        assert result["status"] == "error"

    async def test_trading_days_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.request_trading_days.return_value = (
            RET_OK,
            [{"time": "2026-01-02", "trade_date_type": "WHOLE"}],
        )
        result = await handler.get_trading_days("HK", "2026-01-01", "2026-01-31")
        assert result["status"] == "success"
        assert result["data"][0]["trade_date_type"] == "WHOLE"

    async def test_history_kl_quota_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_history_kl_quota.return_value = (
            RET_OK,
            (2, 298, [{"code": "US.MU", "name": "美光科技", "request_time": "2026-08-21 10:26:32"}]),
        )
        result = await handler.get_history_kl_quota(True)
        assert result["status"] == "success"
        assert result["quota_used"] == 2
        assert result["quota_remaining"] == 298
        assert result["data"][0]["code"] == "US.MU"

    async def test_market_state_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_market_state.return_value = (
            RET_OK,
            pd.DataFrame([{"code": "HK.00700", "stock_name": "腾讯控股", "market_state": "CLOSED"}]),
        )
        result = await handler.get_market_state(["HK.00700"])
        assert result["status"] == "success"
        assert result["data"][0]["market_state"] == "CLOSED"

    async def test_g8_disconnected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_rehab("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    async def test_g8_failure(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_rehab.return_value = (-1, "fail")
        result = await handler.get_rehab("HK.00700")
        assert result["status"] == "error"


# ── G6 板块轮动前置：标的所属板块（get_owner_plate）─────────────────────
class TestG6OwnerPlate:
    """G6 get_owner_plate：标的→所属板块（与 get_hk_sector_flow 构成双向索引）"""

    async def test_owner_plate_success(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_owner_plate.return_value = (
            RET_OK,
            pd.DataFrame(
                [
                    {
                        "code": "HK.00700",
                        "name": "腾讯控股",
                        "plate_code": "HK.LIST23586",
                        "plate_name": "人工智能",
                        "plate_type": "CONCEPT",
                    }
                ]
            ),
        )
        result = await handler.get_owner_plate("HK.00700")
        assert result["status"] == "success"
        assert result["data"][0]["plate_name"] == "人工智能"
        assert result["data"][0]["plate_type"] == "CONCEPT"

    async def test_owner_plate_unsupported(self):
        handler, conn_mgr, _ = _make_handler()
        result = await handler.get_owner_plate(
            "GC=F", is_unsupported_func=lambda t: t.startswith("GC"), format_ticker_func=lambda t: t
        )
        assert result["status"] == "error"

    async def test_owner_plate_disconnected(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx = None
        result = await handler.get_owner_plate("HK.00700")
        assert result["status"] == "error"
        assert "未连接" in result["message"]

    async def test_owner_plate_failure(self):
        handler, conn_mgr, _ = _make_handler()
        conn_mgr.quote_ctx.get_owner_plate.return_value = (-1, "fail")
        result = await handler.get_owner_plate("HK.00700")
        assert result["status"] == "error"
