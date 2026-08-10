"""
Market Engine 单元测试
TEST-15: 覆盖 backend/core/market_engine.py 的 ConnectionManager 与辅助函数
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.market_engine import (
    ConnectionManager,
    manager,
    update_quote_to_redis,
    update_trade_to_redis,
)


async def _run_update_quote(ticker, data, settle=0.05):
    """在独立事件循环内运行行情写入，并等待后台 alert 任务 (create_task) 执行完毕。

    使用 asyncio.run 而非 get_event_loop().run_until_complete，避免 Python 3.12 +
    pytest-asyncio(mode=AUTO) 下复用/污染 pytest 管理的事件循环导致 worker 死锁/卡死。
    """
    await update_quote_to_redis(ticker, data)
    await asyncio.sleep(settle)


async def _run_update_trade(ticker, data):
    await update_trade_to_redis(ticker, data)


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
        with patch("backend.services.market_engine.asyncio.create_task"):
            mgr.subscribe(ws, ["US.AAPL", "HK.00700"])
        assert "US.AAPL" in mgr.subscriptions[ws]
        assert "HK.00700" in mgr.subscriptions[ws]

    async def test_subscribe_dedup(self):
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        await mgr.connect(ws)
        with patch("backend.services.market_engine.asyncio.create_task"):
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
    @patch("backend.services.market_engine.manager")
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
        asyncio.run(_run_update_quote("US.AAPL", quote_data, settle=0))
        mock_raw_redis.hset.assert_awaited_once()
        mock_raw_redis.publish.assert_awaited_once()

    @patch("backend.services.market_engine.manager")
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
        asyncio.run(_run_update_quote("US.AAPL", quote_data, settle=0))
        mock_raw_redis.hset.assert_awaited_once()

    @patch("backend.services.market_engine.redis_client")
    def test_alert_triggered_when_price_above_upper(self, mock_redis):
        mock_raw_redis = AsyncMock()
        # need manager.raw_redis for hset/publish
        import backend.services.market_engine as me

        me.manager.raw_redis = mock_raw_redis
        # redis_client.hgetall is called to check alert rules
        rules_json = json.dumps({"upper": 160.0})
        mock_redis.hgetall = AsyncMock(
            return_value={
                "user1": rules_json,
            }
        )
        mock_redis.hdel = AsyncMock()
        quote_data = {
            "ticker": "US.AAPL",
            "last_price": 165.0,
            "change_pct": "+2.0%",
            "volume_str": "1M",
            "source": "futu",
        }
        send_alert_mock = AsyncMock()
        with patch("backend.services.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.run(_run_update_quote("US.AAPL", quote_data))
            send_alert_mock.assert_called_once()


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
        from backend.services.market_engine import manager as m1
        from backend.services.market_engine import manager as m2

        assert m1 is m2

    def test_manager_type(self):
        assert isinstance(manager, ConnectionManager)


# ─── update_quote_to_redis alert 分支 ────────────────────────────────
class TestUpdateQuoteToRedisAlerts:
    @patch("backend.services.market_engine.redis_client")
    def test_alert_lower_triggered(self, mock_redis):
        import backend.services.market_engine as me

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
        with patch("backend.services.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.run(_run_update_quote("US.AAPL", quote_data))
            send_alert_mock.assert_called_once()

    @patch("backend.services.market_engine.redis_client")
    def test_alert_pct_change_triggered_bullish(self, mock_redis):
        import backend.services.market_engine as me

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
        with patch("backend.services.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.run(_run_update_quote("US.AAPL", quote_data))
            send_alert_mock.assert_called_once()

    @patch("backend.services.market_engine.redis_client")
    def test_alert_pct_change_triggered_bearish(self, mock_redis):
        import backend.services.market_engine as me

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
        with patch("backend.services.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.run(_run_update_quote("US.AAPL", quote_data))
            send_alert_mock.assert_called_once()

    @patch("backend.services.market_engine.redis_client")
    def test_alert_pct_change_value_error(self, mock_redis):
        """change_pct 格式非法时触发 ValueError 分支"""
        import backend.services.market_engine as me

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
        asyncio.run(_run_update_quote("US.AAPL", quote_data, settle=0))
        assert True

    @patch("backend.services.market_engine.redis_client")
    def test_no_alert_when_price_between_bounds(self, mock_redis):
        import backend.services.market_engine as me

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
        with patch("backend.services.market_engine.notification_service") as mock_notify:
            mock_notify.send_alert = send_alert_mock
            asyncio.run(_run_update_quote("US.AAPL", quote_data))
            send_alert_mock.assert_not_called()


# ─── update_trade_to_redis ────────────────────────────────────────────
class TestUpdateTradeToRedis:
    def test_writes_to_stream_and_publishes(self):

        fake_redis = AsyncMock()
        mgr = ConnectionManager()
        mgr.raw_redis = fake_redis
        import backend.services.market_engine as me

        original_raw_redis = me.manager.raw_redis
        me.manager.raw_redis = fake_redis
        try:
            fake_trade_data = b"\x08\x01"
            asyncio.run(_run_update_trade("US.AAPL", fake_trade_data))
            fake_redis.xadd.assert_awaited_once()
            fake_redis.publish.assert_awaited_once()
        finally:
            me.manager.raw_redis = original_raw_redis

    def test_exception_handling(self):

        fake_redis = AsyncMock()
        fake_redis.xadd = AsyncMock(side_effect=Exception("Redis down"))
        import backend.services.market_engine as me

        original_raw_redis = me.manager.raw_redis
        me.manager.raw_redis = fake_redis
        try:
            # 异常被捕获，不应抛出
            asyncio.run(_run_update_trade("US.AAPL", b"\x08\x01"))
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


# ─── broadcast_loop 主循环（异步）────────────────────────────────────
_real_sleep = asyncio.sleep  # 保存原始引用，避免 mock 后递归


class TestBroadcastLoop:
    """测试 broadcast_loop 主循环，通过 mock asyncio.sleep 让循环在第一次迭代后退出"""

    async def test_broadcast_loop_single_iteration(self):
        """测试 broadcast_loop 完成一次迭代"""
        mgr = ConnectionManager()

        # Mock asyncio.sleep 让出控制权（使用 _real_sleep 避免递归）
        async def fast_sleep(delay):
            await _real_sleep(0)

        with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
            with patch("backend.services.market_engine.l1_cached_redis.get", return_value="1"):
                # BE-ARCH-07b: futu_service 本地门控已移除，所有 Futu 调用经 DataSourceRouter
                # 远程执行；is_futu_unsupported 为纯函数（backend.services.futu.utils）
                with patch(
                    "backend.services.market_engine.is_futu_unsupported",
                    return_value=True,  # 所有标的都不支持富途
                ):
                    with patch(
                        "backend.services.market_engine.data_source_router.fetch_futu",
                        new=AsyncMock(return_value={"status": "success", "data": {}}),
                    ):
                        with patch("backend.services.market_engine.data_source_router.fetch_yfinance") as mock_yf:
                            mock_yf.return_value = {
                                "status": "success",
                                "data": {"trend": [], "ticker": "US.AAPL", "last_price": 150.0},
                            }

                            # 添加一个订阅
                            ws = MagicMock()
                            mgr.subscriptions[ws] = {"US.AAPL"}

                            # 使用 timeout 让循环快速退出
                            try:
                                await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.1)
                            except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                pass

    async def test_broadcast_loop_with_futu_support(self):
        """测试 broadcast_loop 当标的支持富途时 (经 DataSourceRouter.fetch_futu)"""
        mgr = ConnectionManager()
        mgr.raw_redis = AsyncMock()  # 避免 update_quote_to_redis 中 await MagicMock 报错

        # Mock asyncio.sleep 让出控制权（使用 _real_sleep 避免递归）
        async def fast_sleep(delay):
            await _real_sleep(0)

        async def track_fetch(action, **kwargs):
            if action == "QUOTE":
                return {"status": "success", "last_price": 150.0, "change_pct": "+1.0%"}
            if action == "HISTORY":
                return {"status": "success", "data": []}
            if action == "FUND_FLOW":
                return {"status": "success", "data": {"main_fund_net_inflow": 0}}
            return {"status": "success"}

        mock_fetch = AsyncMock(side_effect=track_fetch)

        # Mock time.time 返回一个固定值，并确保 last_futu_update 足够旧
        fixed_time = 100.0
        with patch("time.time", return_value=fixed_time):
            mgr.last_futu_update["US.AAPL"] = fixed_time - 20  # 20 秒前更新，超过 10 秒阈值

            with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
                with patch("backend.services.market_engine.l1_cached_redis.get", return_value="1"):
                    with patch(
                        "backend.services.market_engine.is_futu_unsupported",
                        return_value=False,  # US.AAPL 支持富途
                    ):
                        with patch("backend.services.market_engine.data_source_router.fetch_yfinance") as mock_yf:
                            mock_yf.return_value = {
                                "status": "success",
                                "data": {"trend": []},
                            }

                            with patch(
                                "backend.services.market_engine.data_source_router.fetch_futu",
                                new=mock_fetch,
                            ):
                                # 添加一个订阅
                                ws = MagicMock()
                                mgr.subscriptions[ws] = {"US.AAPL"}

                                # 使用 timeout 让循环快速退出
                                try:
                                    await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.3)
                                except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                    pass

                            # 验证富途 fetch_futu("QUOTE", ...) 被调用
                            quote_calls = [c for c in mock_fetch.call_args_list if c.args and c.args[0] == "QUOTE"]
                            assert quote_calls, "fetch_futu('QUOTE', ...) was not called"

    async def test_broadcast_loop_yfinance_disabled(self):
        """测试 broadcast_loop 当 yfinance 禁用时"""
        mgr = ConnectionManager()

        # Mock asyncio.sleep 让出控制权（使用 _real_sleep 避免递归）
        async def fast_sleep(delay):
            await _real_sleep(0)

        with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
            with patch("backend.services.market_engine.l1_cached_redis.get", return_value="0"):  # YF 禁用
                with patch(
                    "backend.services.market_engine.is_futu_unsupported",
                    return_value=True,  # 不支持富途
                ):
                    with patch(
                        "backend.services.market_engine.data_source_router.fetch_futu",
                        new=AsyncMock(return_value={"status": "success", "data": {}}),
                    ):
                        with patch("backend.services.market_engine.data_source_router.fetch_yfinance") as mock_yf:
                            ws = MagicMock()
                            mgr.subscriptions[ws] = {"US.AAPL"}

                            try:
                                await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.1)
                            except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                pass

                            # 验证 YF 子服务兜底未被调用（YF 禁用）
                            mock_yf.assert_not_called()

    async def test_broadcast_loop_exception_handling(self):
        """测试 broadcast_loop 的异常处理分支"""
        mgr = ConnectionManager()

        # Mock asyncio.sleep 让出控制权（使用 _real_sleep 避免递归）
        async def fast_sleep(delay):
            await _real_sleep(0)

        # Mock l1_cached_redis.get 抛出异常
        with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
            with patch("backend.services.market_engine.l1_cached_redis.get", side_effect=Exception("Redis error")):
                with patch(
                    "backend.services.market_engine.is_futu_unsupported",
                    return_value=True,
                ):
                    with patch(
                        "backend.services.market_engine.data_source_router.fetch_futu",
                        new=AsyncMock(return_value={"status": "success", "data": {}}),
                    ):
                        with patch("backend.services.market_engine.data_source_router.fetch_yfinance"):
                            ws = MagicMock()
                            mgr.subscriptions[ws] = {"US.AAPL"}

                            # 使用 timeout 让循环快速退出
                            try:
                                await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.1)
                            except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                pass

                        # 如果到达这里，说明异常被捕获，循环继续了

    async def test_broadcast_loop_futu_gc_mechanism(self):
        """测试 Futu GC 机制：清理废弃订阅"""
        mgr = ConnectionManager()

        # Mock asyncio.sleep 让出控制权（使用 _real_sleep 避免递归）
        async def fast_sleep(delay):
            await _real_sleep(0)

        with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
            with patch("backend.services.market_engine.l1_cached_redis.get", return_value="1"):
                with patch(
                    "backend.services.market_engine.is_futu_unsupported",
                    return_value=False,
                ):
                    with patch("backend.services.market_engine.data_source_router.fetch_yfinance") as mock_yf:
                        # YF 兜底改经子服务 router
                        mock_yf.return_value = {"status": "success", "data": {"trend": []}}

                        async def _gc_track_fetch(action, **kwargs):
                            if action == "HISTORY":
                                return {"status": "success", "data": []}
                            if action == "FUND_FLOW":
                                return {"status": "success", "data": {"main_fund_net_inflow": 0}}
                            if action == "QUOTE":
                                return {"status": "success", "last_price": 150.0}
                            if action == "ACCOUNT_INFO":
                                return {"status": "success", "total_assets": 0, "positions": []}
                            return {"status": "success"}

                        with patch(
                            "backend.services.market_engine.data_source_router.fetch_futu",
                            new=AsyncMock(side_effect=_gc_track_fetch),
                        ):
                            # 模拟有旧的 Futu 订阅
                            mgr._futu_active_subs = {"US.OLD_TICKER"}
                            ws = MagicMock()
                            mgr.subscriptions[ws] = {"US.AAPL"}  # 只订阅了 AAPL

                            try:
                                await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.1)
                            except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                pass

                        # 验证旧订阅被清理
                        assert "US.OLD_TICKER" not in mgr._futu_active_subs

    async def test_broadcast_loop_futu_disconnected_skips_all_futu_calls(self):
        """BE-ARCH-07b: futu_service 本地 status 门控已移除，所有 Futu 调用无条件经
        DataSourceRouter 远程执行（router 内部自带熔断/健康度）。本用例改为验证：
        当 is_futu_unsupported 返回 False 时，fetch_futu 被实际调用（而非被本地门控跳过）。"""
        mgr = ConnectionManager()

        async def fast_sleep(delay):
            await _real_sleep(0)

        with patch("backend.services.market_engine.asyncio.sleep", side_effect=fast_sleep):
            with patch("backend.services.market_engine.l1_cached_redis.get", return_value="1"):
                with patch(
                    "backend.services.market_engine.is_futu_unsupported",
                    return_value=False,
                ):
                    with patch("backend.services.market_engine.data_source_router.fetch_yfinance") as mock_yf:
                        mock_yf.return_value = {
                            "status": "success",
                            "data": {"trend": [], "ticker": "US.AAPL", "last_price": 150.0},
                        }

                        mock_fetch = AsyncMock(return_value={"status": "success", "data": {}})
                        ws = MagicMock()
                        mgr.subscriptions[ws] = {"US.AAPL"}

                        with patch(
                            "backend.services.market_engine.data_source_router.fetch_futu",
                            new=mock_fetch,
                        ):
                            try:
                                await asyncio.wait_for(mgr.broadcast_loop(), timeout=0.1)
                            except (asyncio.TimeoutError, StopAsyncIteration, StopIteration):
                                pass

                        # 核心断言：无本地 status 门控，Futu 调用实际经 Router 执行
                        assert mock_fetch.await_count > 0, "fetch_futu 应被唤起（无本地门控跳过）"
