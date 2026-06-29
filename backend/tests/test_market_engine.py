"""
行情引擎核心模块单元测试
覆盖: backend/core/market_engine.py - ConnectionManager 与行情写入函数
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── ConnectionManager 初始化 ─────────────────────────────────────
class TestConnectionManagerInit:
    def test_init_creates_empty_state(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        assert cm.active_connections == []
        assert cm.subscriptions == {}
        assert cm.tech_cache == {}
        assert cm.flow_cache == {}
        assert cm.push_task is None
        assert cm.pubsub_task is None
        assert cm._futu_alert_sent is False
        assert cm._futu_active_subs == set()
        assert cm.raw_redis is not None

    def test_init_default_account_summary(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        assert "总资产" in cm.last_account_summary
        assert "浮动盈亏" in cm.last_account_summary


# ─── ConnectionManager: connect / disconnect ──────────────────────
class TestConnectionManagerConnect:
    async def test_connect_accepts_websocket(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.start_background_tasks = AsyncMock()
        ws = MagicMock()
        ws.accept = AsyncMock()

        await cm.connect(ws)

        ws.accept.assert_called_once()
        assert ws in cm.active_connections
        assert ws in cm.subscriptions
        cm.start_background_tasks.assert_called_once()

    async def test_disconnect_removes_websocket(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.active_connections.append(ws)
        cm.subscriptions[ws] = {"US.AAPL"}

        cm.disconnect(ws)

        assert ws not in cm.active_connections
        assert ws not in cm.subscriptions

    async def test_disconnect_unknown_websocket_noop(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws_unknown = MagicMock()
        # 不应抛异常
        cm.disconnect(ws_unknown)
        assert cm.active_connections == []


# ─── ConnectionManager: subscribe / unsubscribe ───────────────────
class TestConnectionManagerSubscribe:
    async def test_subscribe_adds_tickers(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.subscriptions[ws] = set()
        cm._catch_up_or_snapshot = AsyncMock()

        cm.subscribe(ws, ["US.AAPL", "HK.00700"])

        assert "US.AAPL" in cm.subscriptions[ws]
        assert "HK.00700" in cm.subscriptions[ws]

    async def test_subscribe_unknown_websocket_noop(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm._catch_up_or_snapshot = AsyncMock()

        cm.subscribe(ws, ["US.AAPL"])
        # 未知 ws 不应被加入 subscriptions
        assert ws not in cm.subscriptions

    def test_unsubscribe_removes_tickers(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.subscriptions[ws] = {"US.AAPL", "HK.00700"}

        cm.unsubscribe(ws, ["US.AAPL"])
        assert "US.AAPL" not in cm.subscriptions[ws]
        assert "HK.00700" in cm.subscriptions[ws]

    def test_unsubscribe_unknown_websocket_noop(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        # 不应抛异常
        cm.unsubscribe(ws, ["US.AAPL"])


# ─── ConnectionManager: get_all_subscribed_tickers ────────────────
class TestConnectionManagerGetAllTickers:
    def test_returns_default_macro_tickers(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        tickers = cm.get_all_subscribed_tickers()
        # 默认应包含核心宏观/ETF 标的
        assert "US.VIX" in tickers
        assert "US.SPX" in tickers
        assert "US.SPY" in tickers
        assert "US.QQQ" in tickers
        assert "BTC-USD" in tickers
        assert "JPY=X" in tickers

    def test_includes_user_subscriptions(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        ws = MagicMock()
        cm.subscriptions[ws] = {"US.AAPL", "HK.00700"}

        tickers = cm.get_all_subscribed_tickers()
        assert "US.AAPL" in tickers
        assert "HK.00700" in tickers

    def test_returns_set_type(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        result = cm.get_all_subscribed_tickers()
        assert isinstance(result, set)


# ─── ConnectionManager: _get_yf_fast_info 标的映射 ────────────────
class TestGetYfFastInfo:
    def test_hk_index_mapping_hsi(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 17000.0
            info.previous_close = 16800.0
            info.last_volume = 1000000
            mock_ticker.return_value.fast_info = info

            result = cm._get_yf_fast_info("HK.800000")
            assert result["status"] == "success"
            assert result["ticker"] == "HK.800000"
            assert result["source"] == "yfinance"
            # 验证映射到 ^HSI
            mock_ticker.assert_called_once_with("^HSI")

    def test_hk_index_mapping_hstech(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 3800.0
            info.previous_close = 3750.0
            info.last_volume = 500000
            mock_ticker.return_value.fast_info = info

            cm._get_yf_fast_info("HK.800700")
            mock_ticker.assert_called_once_with("^HSTECH")

    def test_hk_index_mapping_hsce(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 6000.0
            info.previous_close = 5950.0
            info.last_volume = 300000
            mock_ticker.return_value.fast_info = info

            cm._get_yf_fast_info("HK.800100")
            mock_ticker.assert_called_once_with("^HSCE")

    def test_hk_stock_mapping(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 400.0
            info.previous_close = 395.0
            info.last_volume = 1000000
            mock_ticker.return_value.fast_info = info

            cm._get_yf_fast_info("HK.00700")
            mock_ticker.assert_called_once_with("00700.HK")

    def test_us_stock_mapping(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 190.0
            info.previous_close = 185.0
            info.last_volume = 5000000
            mock_ticker.return_value.fast_info = info

            cm._get_yf_fast_info("US.AAPL")
            mock_ticker.assert_called_once_with("AAPL")

    def test_change_pct_calculation(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        with patch("yfinance.Ticker") as mock_ticker:
            info = MagicMock()
            info.last_price = 110.0
            info.previous_close = 100.0
            info.last_volume = 1000
            mock_ticker.return_value.fast_info = info

            result = cm._get_yf_fast_info("US.AAPL")
            assert "+10.00%" in result["change_pct"]


# ─── ConnectionManager: _fetch_fallback_quote ─────────────────────
class TestFetchFallbackQuote:
    async def test_fetch_fallback_quote_success(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm._get_yf_fast_info = MagicMock(return_value={"status": "success"})

        result = await cm._fetch_fallback_quote("US.AAPL")
        assert result["status"] == "success"

    async def test_fetch_fallback_quote_timeout(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()

        def slow_call(ticker):
            import time

            time.sleep(5)
            return {"status": "success"}

        cm._get_yf_fast_info = MagicMock(side_effect=slow_call)
        result = await cm._fetch_fallback_quote("US.AAPL")
        assert result["status"] == "error"


# ─── update_quote_to_redis 模块级函数 ─────────────────────────────
class TestUpdateQuoteToRedis:
    async def test_write_basic_quote(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.redis_client = AsyncMock()
        market_engine.redis_client.hgetall = AsyncMock(return_value={})

        quote = {
            "ticker": "US.AAPL",
            "last_price": 190.0,
            "change_pct": "+1.5%",
            "volume_str": "10M",
            "source": "yfinance",
            "bids": [{"price": 189.5, "size": 100}],
            "asks": [{"price": 190.5, "size": 200}],
        }
        await market_engine.update_quote_to_redis("US.AAPL", quote)
        market_engine.manager.raw_redis.hset.assert_called_once()
        market_engine.manager.raw_redis.publish.assert_called_once()

    async def test_write_skips_alerts_when_no_rules(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.redis_client = AsyncMock()
        market_engine.redis_client.hgetall = AsyncMock(return_value={})

        quote = {"ticker": "US.AAPL", "last_price": 190.0, "source": "yfinance"}
        # 不应抛异常
        await market_engine.update_quote_to_redis("US.AAPL", quote)

    async def test_write_triggers_upper_breakout_alert(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.redis_client = AsyncMock()
        market_engine.redis_client.hgetall = AsyncMock(
            return_value={b"user123": b'{"upper": 200.0, "lower": null, "pct_change": null}'}
        )
        market_engine.redis_client.hdel = AsyncMock()
        market_engine.notification_service = AsyncMock()
        market_engine.notification_service.send_alert = AsyncMock()

        quote = {
            "ticker": "US.AAPL",
            "last_price": 205.0,  # 突破 upper=200
            "change_pct": "+2.0%",
            "source": "yfinance",
        }
        await market_engine.update_quote_to_redis("US.AAPL", quote)
        market_engine.redis_client.hdel.assert_called_once()

    async def test_write_triggers_lower_breakdown_alert(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.redis_client = AsyncMock()
        market_engine.redis_client.hgetall = AsyncMock(
            return_value={b"user456": b'{"upper": null, "lower": 100.0, "pct_change": null}'}
        )
        market_engine.redis_client.hdel = AsyncMock()

        quote = {
            "ticker": "US.AAPL",
            "last_price": 95.0,  # 跌破 lower=100
            "change_pct": "-3.0%",
            "source": "yfinance",
        }
        await market_engine.update_quote_to_redis("US.AAPL", quote)
        market_engine.redis_client.hdel.assert_called_once()

    async def test_write_triggers_pct_change_alert(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.redis_client = AsyncMock()
        market_engine.redis_client.hgetall = AsyncMock(
            return_value={b"user789": b'{"upper": null, "lower": null, "pct_change": 5.0}'}
        )
        market_engine.redis_client.hdel = AsyncMock()

        quote = {
            "ticker": "US.AAPL",
            "last_price": 195.0,
            "change_pct": "+6.0%",  # 涨幅超过 5%
            "source": "yfinance",
        }
        await market_engine.update_quote_to_redis("US.AAPL", quote)
        market_engine.redis_client.hdel.assert_called_once()

    async def test_write_handles_exception_gracefully(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.manager.raw_redis.hset = AsyncMock(side_effect=Exception("Redis down"))
        # 不应抛异常
        await market_engine.update_quote_to_redis("US.AAPL", {"last_price": 100.0})


# ─── update_trade_to_redis 模块级函数 ─────────────────────────────
class TestUpdateTradeToRedis:
    async def test_write_trade_success(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        trade_data = b"\x01\x02\x03\x04"

        await market_engine.update_trade_to_redis("US.AAPL", trade_data)
        market_engine.manager.raw_redis.xadd.assert_called_once()
        market_engine.manager.raw_redis.publish.assert_called_once_with(
            "quant:trades:stream", trade_data
        )

    async def test_write_trade_handles_exception(self):
        from backend.core import market_engine

        market_engine.manager.raw_redis = AsyncMock()
        market_engine.manager.raw_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))
        # 不应抛异常
        await market_engine.update_trade_to_redis("US.AAPL", b"data")


# ─── _catch_up_or_snapshot 断线追补 ───────────────────────────────
class TestCatchUpOrSnapshot:
    async def test_snapshot_no_last_id(self):
        """无 last_id 时直接发送最新缓存快照"""
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.raw_redis = AsyncMock()
        cm.raw_redis.hget = AsyncMock(return_value=b"cached_quote_bytes")
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        cm.active_connections.append(ws)

        await cm._catch_up_or_snapshot(ws, ["US.AAPL"], {})
        cm.raw_redis.hget.assert_called_once()
        ws.send_bytes.assert_called_once_with(b"cached_quote_bytes")

    async def test_catch_up_with_last_id(self):
        """有 last_id 时通过 XRANGE 追补错过的消息"""
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.raw_redis = AsyncMock()
        cm.raw_redis.xrange = AsyncMock(
            return_value=[(b"1234-0", {b"payload": b"msg1"}), (b"1235-0", {b"payload": b"msg2"})]
        )
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        cm.active_connections.append(ws)

        await cm._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "1233-0"})
        cm.raw_redis.xrange.assert_called_once()
        assert ws.send_bytes.call_count == 2

    async def test_catch_up_batch_compression(self):
        """超过 100 条消息触发批量压缩"""
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.raw_redis = AsyncMock()
        # 制造 150 条消息
        missed = [(f"msg-{i}".encode(), {b"payload": b"x" * 10}) for i in range(150)]
        cm.raw_redis.xrange = AsyncMock(return_value=missed)
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        cm.active_connections.append(ws)

        await cm._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "old-id"})
        # 应只调用 1 次 send_bytes（批量压缩）
        ws.send_bytes.assert_called_once()

    async def test_catch_up_handles_exception(self):
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.raw_redis = AsyncMock()
        cm.raw_redis.xrange = AsyncMock(side_effect=Exception("Redis down"))
        ws = MagicMock()

        # 不应抛异常
        await cm._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "old-id"})

    async def test_catch_up_no_payloads_continues(self):
        """XRANGE 返回空时安全跳过"""
        from backend.core.market_engine import ConnectionManager

        cm = ConnectionManager()
        cm.raw_redis = AsyncMock()
        cm.raw_redis.xrange = AsyncMock(return_value=[])
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        cm.active_connections.append(ws)

        await cm._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "old-id"})
        ws.send_bytes.assert_not_called()
