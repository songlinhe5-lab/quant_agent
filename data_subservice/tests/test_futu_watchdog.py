"""FutuWatchdog 单元测试 — 覆盖健康探针、重连、订阅恢复、stop/stats 分支 (mock 网络/事件循环 sleep)。"""

import asyncio
from unittest.mock import MagicMock

from futu import RET_OK

import data_subservice.futu_src.watchdog as wd_mod
from data_subservice.futu_src.watchdog import FutuWatchdog


class _FakeCacheMgr:
    def __init__(self):
        self._topics = set()

    @property
    def subscribed_topics(self):
        return self._topics

    @property
    def subscription_count(self):
        return len(self._topics)

    @property
    def max_subscriptions(self):
        return 100

    def touch_topic(self, ticker, st):
        self._topics.add((ticker, st))


class _FakeConnMgr:
    def __init__(self, status="CONNECTED", quote_ctx=None, error_msg=""):
        self.status = status
        self.quote_ctx = quote_ctx
        self.error_msg = error_msg


class _FakeFutu:
    def __init__(self, conn_mgr, cache_mgr, connect_raises=False, close_raises=False):
        self.conn_mgr = conn_mgr
        self.cache_mgr = cache_mgr
        self._connect_raises = connect_raises
        self._close_raises = close_raises
        self.close_called = False
        self.connect_called = False

    def close(self):
        self.close_called = True
        if self._close_raises:
            raise RuntimeError("close boom")

    def connect(self):
        self.connect_called = True
        if self._connect_raises:
            raise RuntimeError("connect boom")
        self.conn_mgr.status = "CONNECTED"


def _make_wd(
    conn_status="CONNECTED", quote_ctx=None, cache_topics=None, connect_raises=False, close_raises=False, error_msg=""
):
    cm = _FakeConnMgr(conn_status, quote_ctx, error_msg)
    ccm = _FakeCacheMgr()
    if cache_topics:
        ccm._topics = set(cache_topics)
    futu = _FakeFutu(cm, ccm, connect_raises=connect_raises, close_raises=close_raises)
    return FutuWatchdog(futu), futu


# ─── _health_check ──────────────────────────────────────────────────
class TestHealthCheck:
    def test_connected_ok(self, monkeypatch):
        wd, futu = _make_wd(quote_ctx=MagicMock())
        wd._conn_mgr.quote_ctx.get_global_state = lambda: (RET_OK, {"state": 1})
        assert asyncio.run(wd._health_check()) is True

    def test_not_connected(self):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock())
        assert asyncio.run(wd._health_check()) is False

    def test_no_quote_ctx(self):
        wd, futu = _make_wd(conn_status="CONNECTED", quote_ctx=None)
        assert asyncio.run(wd._health_check()) is False
        assert wd._conn_mgr.status == "DISCONNECTED"

    def test_probe_ret_not_ok(self, monkeypatch):
        wd, futu = _make_wd(quote_ctx=MagicMock())
        wd._conn_mgr.quote_ctx.get_global_state = lambda: (1, None)
        assert asyncio.run(wd._health_check()) is False
        assert wd._conn_mgr.status == "DISCONNECTED"

    def test_probe_exception(self, monkeypatch):
        wd, futu = _make_wd(quote_ctx=MagicMock())

        def boom():
            raise RuntimeError("x")

        wd._conn_mgr.quote_ctx.get_global_state = boom
        assert asyncio.run(wd._health_check()) is False


# ─── _do_reconnect ──────────────────────────────────────────────────
class TestDoReconnect:
    def test_success(self, monkeypatch):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock())
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        assert asyncio.run(wd._do_reconnect()) is True
        assert futu.connect_called is True
        assert wd._conn_mgr.status == "CONNECTED"

    def test_connect_raises(self, monkeypatch):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock(), connect_raises=True)
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        assert asyncio.run(wd._do_reconnect()) is False

    def test_close_raises_ignored(self, monkeypatch):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock(), close_raises=True)
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        # close 抛异常被吞, 重连仍成功
        assert asyncio.run(wd._do_reconnect()) is True

    def test_reconnect_verify_fails(self, monkeypatch):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock())
        # connect 后 status 不置 CONNECTED -> 验证失败
        futu.connect = lambda: None
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        assert asyncio.run(wd._do_reconnect()) is False

    def test_wait_for_timeout(self, monkeypatch):
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock())

        async def slow_coro():
            await asyncio.sleep(0)  # 占位

        def wait_for_timeout(coro, timeout=None):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(wd_mod.asyncio, "wait_for", wait_for_timeout)
        assert asyncio.run(wd._do_reconnect()) is False


# ─── _restore_subscriptions ─────────────────────────────────────────
class TestRestoreSubscriptions:
    def test_empty_returns_early(self, monkeypatch):
        wd, futu = _make_wd(cache_topics=[])
        # 不应调用 quote_ctx.subscribe
        assert asyncio.run(wd._restore_subscriptions()) is None

    def test_restores(self, monkeypatch):
        wd, _ = _make_wd(cache_topics=[("HK.00700", "QUOTE")])
        sub = MagicMock()
        sub.subscribe = lambda *a, **k: (RET_OK, None)
        wd._conn_mgr.quote_ctx = sub
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        asyncio.run(wd._restore_subscriptions())
        # 订阅成功后 LRU 被 touch
        assert ("HK.00700", "QUOTE") in wd._futu.cache_mgr.subscribed_topics

    def test_subscribe_failure_logged(self, monkeypatch):
        wd, futu = _make_wd(cache_topics=[("HK.00700", "QUOTE")])
        sub = MagicMock()
        sub.subscribe = lambda *a, **k: (1, "err")
        wd._conn_mgr.quote_ctx = sub
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)
        asyncio.run(wd._restore_subscriptions())  # 不应抛


# ─── stop / stats ───────────────────────────────────────────────────
class TestStopAndStats:
    def test_stop_cancels_task(self):
        wd, futu = _make_wd()
        wd._running = True
        wd._task = MagicMock(done=MagicMock(return_value=False))
        wd.stop()
        assert wd._running is False
        wd._task.cancel.assert_called_once()

    def test_stats(self):
        wd, futu = _make_wd(conn_status="CONNECTED")
        wd._total_reconnects = 3
        wd._consecutive_failures = 1
        s = wd.stats
        assert s["running"] is False
        assert s["total_reconnects"] == 3
        assert s["connection_status"] == "CONNECTED"


# ─── _watchdog_loop 单轮 ────────────────────────────────────────────
class TestWatchdogLoopSingleRound:
    def test_one_unhealthy_round_then_stop(self, monkeypatch):
        """health_check 返回 False -> 重连 -> 设 _running=False 退出。"""
        wd, futu = _make_wd(conn_status="DISCONNECTED", quote_ctx=MagicMock())

        async def fake_sleep(d):
            return None

        monkeypatch.setattr(wd_mod.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(wd_mod.asyncio, "wait_for", lambda coro, timeout=None: coro)

        # 让 health_check 返回 False
        async def fake_health():
            return False

        monkeypatch.setattr(wd, "_health_check", fake_health)

        # 重连后停止循环
        async def fake_reconnect():
            wd._running = False
            return False

        monkeypatch.setattr(wd, "_do_reconnect", fake_reconnect)

        # 同步执行循环一轮
        asyncio.run(wd._watchdog_loop())
        assert wd._running is False

    def test_healthy_round_sleeps_then_stop(self, monkeypatch):
        wd, futu = _make_wd(conn_status="CONNECTED", quote_ctx=MagicMock())
        wd._conn_mgr.quote_ctx.get_global_state = lambda: (RET_OK, {"s": 1})

        calls = {"n": 0}

        async def fake_sleep(d):
            calls["n"] += 1
            wd._running = False  # 第一次健康睡眠后退出
            return None

        monkeypatch.setattr(wd_mod.asyncio, "sleep", fake_sleep)

        async def fake_health():
            return True

        monkeypatch.setattr(wd, "_health_check", fake_health)

        wd._running = True
        asyncio.run(wd._watchdog_loop())
        assert calls["n"] == 1
