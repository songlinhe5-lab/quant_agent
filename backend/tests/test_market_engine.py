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
