"""
Market Engine 单元测试
TEST-15: 覆盖 backend/core/market_engine.py 的 ConnectionManager 与辅助函数
"""

import asyncio
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.core.market_engine import ConnectionManager, manager, update_quote_to_redis


# ─── ConnectionManager 基础行为 ────────────────────────────────────────
class TestConnectionManagerInit:
    def test_init_state(self):
        mgr = ConnectionManager()
        assert mgr.active_connections == []
        assert mgr.subscriptions == {}
        assert mgr.push_task is None
        assert mgr.pubsub_task is None
        assert isinstance(mgr.tech_cache, dict)
        assert isinstance(mgr.flow_cache, dict)

    def test_get_all_subscribed_tickers_includes_macro(self):
        mgr = ConnectionManager()
        result = mgr.get_all_subscribed_tickers()
        assert "US.VIX" in result
        assert "US.SPX" in result
        assert "BTC-USD" in result
        assert "SH.510300" in result

    def test_get_all_subscribed_tickers_includes_subscribed(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"US.AAPL", "HK.00700"}
        result = mgr.get_all_subscribed_tickers()
        assert "US.AAPL" in result
        assert "HK.00700" in result


class TestConnectDisconnect:
    async def test_connect(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)
        assert ws in mgr.active_connections
        assert ws in mgr.subscriptions
        assert mgr.subscriptions[ws] == set()

    async def test_disconnect(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)
        assert ws in mgr.active_connections
        mgr.disconnect(ws)
        assert ws not in mgr.active_connections
        assert ws not in mgr.subscriptions

    def test_disconnect_idempotent(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.disconnect(ws)  # should not raise
        assert True


class TestSubscribeUnsubscribe:
    async def test_subscribe(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)
        with patch("backend.core.market_engine.asyncio.create_task"):
            mgr.subscribe(ws, ["US.AAPL", "HK.00700"])
        assert "US.AAPL" in mgr.subscriptions[ws]
        assert "HK.00700" in mgr.subscriptions[ws]

    async def test_subscribe_dedup(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)
        with patch("backend.core.market_engine.asyncio.create_task"):
            mgr.subscribe(ws, ["US.AAPL"])
            mgr.subscribe(ws, ["US.AAPL", "HK.00700"])
        assert len(mgr.subscriptions[ws]) == 2

    def test_unsubscribe(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"US.AAPL", "HK.00700"}
        mgr.unsubscribe(ws, ["US.AAPL"])
        assert "US.AAPL" not in mgr.subscriptions[ws]
        assert "HK.00700" in mgr.subscriptions[ws]

    def test_unsubscribe_nonexistent(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.subscriptions[ws] = set()
        mgr.unsubscribe(ws, ["NONEXISTENT"])
        assert True


class TestCatchUpOrSnapshot:
    async def test_snapshot_no_cache(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.raw_redis = AsyncMock()
        mgr.raw_redis.hget = AsyncMock(return_value=None)
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {})
        mgr.raw_redis.hget.assert_awaited_once()

    async def test_snapshot_with_cache(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.raw_redis = AsyncMock()
        mgr.raw_redis.hget = AsyncMock(return_value=b"\x08\x01")
        mgr.active_connections = [ws]
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {})
        ws.send_bytes.assert_called_once()

    async def test_catch_up_with_last_id(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.raw_redis = AsyncMock()
        mgr.raw_redis.xrange = AsyncMock(return_value=[])
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "123"})
        mgr.raw_redis.xrange.assert_awaited_once()


# ─── update_quote_to_redis ─────────────────────────────────────────────
class TestUpdateQuoteToRedis:
    @patch("backend.core.market_engine.manager")
    def test_writes_to_redis(self, mock_mgr):
        mock_raw_redis = AsyncMock()
        mock_mgr.raw_redis = mock_raw_redis
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 150.0,
            "change_pct": "+1.0%",
            "volume_str": "1.2M",
            "source": "futu",
            "bids": [{"price": 149.0, "size": 10}],
            "asks": [{"price": 151.0, "size": 10}],
        }
        asyncio.get_event_loop().run_until_complete(
            update_quote_to_redis("US.AAPL", quote_data)
        )
        mock_raw_redis.hset.assert_awaited_once()
        mock_raw_redis.publish.assert_awaited_once()

    @patch("backend.core.market_engine.manager")
    def test_no_alerts_when_price_zero(self, mock_mgr):
        mock_raw_redis = AsyncMock()
        mock_mgr.raw_redis = mock_raw_redis
        mock_mgr.raw_redis.hgetall = AsyncMock(return_value={})
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 0,
            "change_pct": "0%",
            "volume_str": "--",
            "source": "futu",
        }
        asyncio.get_event_loop().run_until_complete(
            update_quote_to_redis("US.AAPL", quote_data)
        )
        mock_raw_redis.hset.assert_awaited_once()

    @patch("backend.core.market_engine.redis_client")
    def test_alert_triggered_when_price_above_upper(self, mock_redis):
        mock_raw_redis = AsyncMock()
        # need manager.raw_redis for hset/publish
        import backend.core.market_engine as me
        me.manager.raw_redis = mock_raw_redis
        # redis_client.hgetall is called to check alert rules
        rules_json = json.dumps({"upper": 160.0})
        mock_redis.hgetall = AsyncMock(return_value={
            "user1": rules_json,
        })
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 165.0,
            "change_pct": "+2.0%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.core.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.get_event_loop().run_until_complete(
                update_quote_to_redis("US.AAPL", quote_data)
            )
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
            send_alert_mock.assert_called_once()


# ─── _get_yf_fast_info ────────────────────────────────────────────────
class TestGetYfFastInfo:
    def test_us_ticker(self):
        mgr = ConnectionManager()
        fake_info = MagicMock()
        fake_info.last_price = 150.0
        fake_info.previous_close = 149.0
        fake_info.last_volume = 1_000_000
        fake_ticker = MagicMock()
        fake_ticker.fast_info = fake_info

        with patch.dict(sys.modules, {"yfinance": MagicMock(Ticker=lambda t: fake_ticker)}):
            result = mgr._get_yf_fast_info("US.AAPL")
            assert result["status"] == "success"
            assert result["ticker"] == "US.AAPL"

    def test_hk_index(self):
        mgr = ConnectionManager()
        fake_info = MagicMock()
        fake_info.last_price = 20000.0
        fake_info.previous_close = 19900.0
        fake_info.last_volume = 0
        fake_ticker = MagicMock()
        fake_ticker.fast_info = fake_info

        with patch.dict(sys.modules, {"yfinance": MagicMock(Ticker=lambda t: fake_ticker)}):
            result = mgr._get_yf_fast_info("HK.800000")
            assert result["status"] == "success"

    def test_vix(self):
        mgr = ConnectionManager()
        fake_info = MagicMock()
        fake_info.last_price = 15.0
        fake_info.previous_close = 14.5
        fake_info.last_volume = 0
        fake_ticker = MagicMock()
        fake_ticker.fast_info = fake_info

        with patch.dict(sys.modules, {"yfinance": MagicMock(Ticker=lambda t: fake_ticker)}):
            result = mgr._get_yf_fast_info("US.VIX")
            assert result["status"] == "success"


# ─── broadcast_loop 核心逻辑分支（同步部分）──────────────────────────
class TestBroadcastLoopBranches:
    def test_get_all_subscribed_tickers_adds_macro_set(self):
        mgr = ConnectionManager()
        tickers = mgr.get_all_subscribed_tickers()
        assert isinstance(tickers, set)
        assert len(tickers) > 10

    def test_tech_cache_eviction(self):
        mgr = ConnectionManager()
        mgr.tech_cache = {"OLD": [], "KEPT": []}
        mgr.subscriptions = {MagicMock(): {"KEPT"}}
        all_tickers = mgr.get_all_subscribed_tickers()
        stale = [t for t in mgr.tech_cache if t not in all_tickers]
        for t in stale:
            del mgr.tech_cache[t]
        assert "OLD" not in mgr.tech_cache

    def test_flow_cache_eviction(self):
        mgr = ConnectionManager()
        mgr.flow_cache = {"OLD": {}, "KEPT": {}}
        mgr.subscriptions = {MagicMock(): {"KEPT"}}
        all_tickers = mgr.get_all_subscribed_tickers()
        stale = [t for t in mgr.flow_cache if t not in all_tickers]
        for t in stale:
            del mgr.flow_cache[t]
        assert "OLD" not in mgr.flow_cache


# ─── manager 全局单例 ─────────────────────────────────────────────────
class TestGlobalManager:
    def test_manager_is_singleton(self):
        from backend.core.market_engine import manager as m1
        from backend.core.market_engine import manager as m2
        assert m1 is m2

    def test_manager_type(self):
        assert isinstance(manager, ConnectionManager)


# ─── update_quote_to_redis alert 分支 ────────────────────────────────
class TestUpdateQuoteToRedisAlerts:
    @patch("backend.core.market_engine.redis_client")
    def test_alert_lower_triggered(self, mock_redis):
        import backend.core.market_engine as me
        me.manager.raw_redis = AsyncMock()
        rules_json = json.dumps({"lower": 140.0})
        mock_redis.hgetall = AsyncMock(return_value={"user1": rules_json})
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 135.0,
            "change_pct": "-3.0%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.core.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.get_event_loop().run_until_complete(
                update_quote_to_redis("US.AAPL", quote_data)
            )
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
            send_alert_mock.assert_called_once()

    @patch("backend.core.market_engine.redis_client")
    def test_alert_pct_change_triggered_bullish(self, mock_redis):
        import backend.core.market_engine as me
        me.manager.raw_redis = AsyncMock()
        rules_json = json.dumps({"pct_change": 2.0})
        mock_redis.hgetall = AsyncMock(return_value={"user1": rules_json})
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 155.0,
            "change_pct": "+3.5%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.core.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.get_event_loop().run_until_complete(
                update_quote_to_redis("US.AAPL", quote_data)
            )
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
            send_alert_mock.assert_called_once()

    @patch("backend.core.market_engine.redis_client")
    def test_alert_pct_change_triggered_bearish(self, mock_redis):
        import backend.core.market_engine as me
        me.manager.raw_redis = AsyncMock()
        rules_json = json.dumps({"pct_change": 2.0})
        mock_redis.hgetall = AsyncMock(return_value={"user1": rules_json})
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 145.0,
            "change_pct": "-3.5%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.core.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.get_event_loop().run_until_complete(
                update_quote_to_redis("US.AAPL", quote_data)
            )
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
            send_alert_mock.assert_called_once()

    @patch("backend.core.market_engine.redis_client")
    def test_alert_pct_change_value_error(self, mock_redis):
        """change_pct 格式非法时触发 ValueError 分支"""
        import backend.core.market_engine as me
        me.manager.raw_redis = AsyncMock()
        rules_json = json.dumps({"pct_change": 2.0})
        mock_redis.hgetall = AsyncMock(return_value={"user1": rules_json})
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 150.0,
            "change_pct": "N/A",  # 无法解析为 float
            "volume_str": "1M",
            "source": "futu",
        }
        # ValueError 被 except 捕获，不应抛异常
        asyncio.get_event_loop().run_until_complete(
            update_quote_to_redis("US.AAPL", quote_data)
        )
        assert True

    @patch("backend.core.market_engine.redis_client")
    def test_no_alert_when_price_between_bounds(self, mock_redis):
        import backend.core.market_engine as me
        me.manager.raw_redis = AsyncMock()
        rules_json = json.dumps({"upper": 160.0, "lower": 140.0})
        mock_redis.hgetall = AsyncMock(return_value={"user1": rules_json})
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 150.0,  # 在区间内
            "change_pct": "+0.5%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.core.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.get_event_loop().run_until_complete(
                update_quote_to_redis("US.AAPL", quote_data)
            )
            asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))
            send_alert_mock.assert_not_called()


# ─── update_trade_to_redis ────────────────────────────────────────────
class TestUpdateTradeToRedis:
    def test_writes_to_stream_and_publishes(self):
        from backend.core.market_engine import update_trade_to_redis
        fake_redis = AsyncMock()
        mgr = ConnectionManager()
        mgr.raw_redis = fake_redis
        import backend.core.market_engine as me
        original_raw_redis = me.manager.raw_redis
        me.manager.raw_redis = fake_redis
        try:
            fake_trade_data = b"\x08\x01"
            asyncio.get_event_loop().run_until_complete(
                update_trade_to_redis("US.AAPL", fake_trade_data)
            )
            fake_redis.xadd.assert_awaited_once()
            fake_redis.publish.assert_awaited_once()
        finally:
            me.manager.raw_redis = original_raw_redis

    def test_exception_handling(self):
        from backend.core.market_engine import update_trade_to_redis
        fake_redis = AsyncMock()
        fake_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))
        import backend.core.market_engine as me
        original_raw_redis = me.manager.raw_redis
        me.manager.raw_redis = fake_redis
        try:
            # 异常被捕获，不应抛出
            asyncio.get_event_loop().run_until_complete(
                update_trade_to_redis("US.AAPL", b"\x08\x01")
            )
            assert True
        finally:
            me.manager.raw_redis = original_raw_redis


# ─── _catch_up_or_snapshot 批量压缩路径 ───────────────────────────────
class TestCatchUpBatchCompress:
    async def test_batch_compress_when_over_100_messages(self):
        mgr = ConnectionManager()
        mgr.raw_redis = AsyncMock()
        ws = MagicMock()
        mgr.active_connections = [ws]
        # 构造 101 条消息
        fake_messages = []
        fake_payload = b"\x08\x01\x12\x05AAPL"
        for i in range(101):
            fake_messages.append((f"id_{i}", {b"payload": fake_payload}))
        mgr.raw_redis.xrange = AsyncMock(return_value=fake_messages)
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "0"})
        # 应该调用压缩发送（send_bytes 被调用）
        ws.send_bytes.assert_called_once()
        sent_data = ws.send_bytes.call_args[0][0]
        assert isinstance(sent_data, bytes)
        assert sent_data[0] == 0x01  # zlib 压缩模式标志

    async def test_small_batch_no_compress(self):
        mgr = ConnectionManager()
        mgr.raw_redis = AsyncMock()
        ws = MagicMock()
        ws.send_bytes = AsyncMock()
        mgr.active_connections = [ws]
        # 构造 2 条消息
        fake_messages = [
            ("id_0", {b"payload": b"\x08\x01"}),
            ("id_1", {b"payload": b"\x08\x02"}),
        ]
        mgr.raw_redis.xrange = AsyncMock(return_value=fake_messages)
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "0"})
        # 应该调用 2 次 send_bytes（每条单独发送）
        assert ws.send_bytes.call_count == 2

    async def test_skip_if_ws_not_in_active_connections(self):
        mgr = ConnectionManager()
        mgr.raw_redis = AsyncMock()
        ws = MagicMock()
        # ws 不在 active_connections 中
        mgr.active_connections = []
        fake_messages = [("id_0", {b"payload": b"\x08\x01"})]
        mgr.raw_redis.xrange = AsyncMock(return_value=fake_messages)
        await mgr._catch_up_or_snapshot(ws, ["US.AAPL"], {"US.AAPL": "0"})
        ws.send_bytes.assert_not_called()


# ─── redis_pubsub_listener ────────────────────────────────────────────
class TestRedisPubSubListener:
    async def test_listener_sends_to_subscribed_ws(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"US.AAPL"}
        mgr.active_connections = [ws]

        import backend.core.market_engine as me
        original_raw_redis = mgr.raw_redis
        fake_redis = AsyncMock()
        mgr.raw_redis = fake_redis

        # 构造 QuoteData protobuf
        from backend.core.proto.market_pb2 import QuoteData
        q = QuoteData()
        q.ticker = "US.AAPL"
        q.last_price = 150.0
        payload = q.SerializeToString()

        async def mock_listen():
            yield {"type": "message", "data": payload}
            raise asyncio.CancelledError()  # 立即退出

        fake_pubsub = AsyncMock()
        fake_pubsub.listen = MagicMock(return_value=mock_listen())
        fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

        # 用 timeout 防止无限阻塞
        try:
            await asyncio.wait_for(mgr.redis_pubsub_listener(), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError, StopAsyncIteration):
            pass

        ws.send_bytes.assert_called_once()

    async def test_listener_skips_non_bytes_data(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        mgr.subscriptions[ws] = {"US.AAPL"}
        mgr.active_connections = [ws]

        fake_redis = AsyncMock()
        mgr.raw_redis = fake_redis

        async def mock_listen():
            yield {"type": "message", "data": 12345}  # 非 bytes
            raise asyncio.CancelledError()

        fake_pubsub = AsyncMock()
        fake_pubsub.listen = MagicMock(return_value=mock_listen())
        fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

        try:
            await asyncio.wait_for(mgr.redis_pubsub_listener(), timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError, StopAsyncIteration):
            pass

        ws.send_bytes.assert_not_called()

    async def test_listener_cancelled_error(self):
        mgr = ConnectionManager()
        # 直接抛 CancelledError，测试 except asyncio.CancelledError 分支
        fake_redis = AsyncMock()
        mgr.raw_redis = fake_redis

        async def mock_listen():
            raise asyncio.CancelledError()

        fake_pubsub = AsyncMock()
        fake_pubsub.listen = MagicMock(return_value=mock_listen())
        fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

        # 不应抛异常
        await mgr.redis_pubsub_listener()
        assert True

    async def test_listener_generic_exception(self):
        mgr = ConnectionManager()
        fake_redis = AsyncMock()
        mgr.raw_redis = fake_redis

        async def mock_listen():
            raise Exception("PubSub connection lost")

        fake_pubsub = AsyncMock()
        fake_pubsub.listen = MagicMock(return_value=mock_listen())
        fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

        # 不应抛异常
        await mgr.redis_pubsub_listener()
        assert True


# ─── _fetch_fallback_quote ────────────────────────────────────────────
class TestFetchFallbackQuote:
    async def test_timeout_returns_error(self):
        mgr = ConnectionManager()
        with patch("backend.core.market_engine.asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await mgr._fetch_fallback_quote("US.AAPL")
            assert result["status"] == "error"

    async def test_exception_returns_error(self):
        mgr = ConnectionManager()
        with patch("backend.core.market_engine.asyncio.to_thread", side_effect=Exception("YF down")):
            result = await mgr._fetch_fallback_quote("US.AAPL")
            assert result["status"] == "error"
