"""
Futu Watchdog 单元测试
覆盖: start/stop/_health_check/_do_reconnect/stats/get_watchdog
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backend.services.futu.watchdog import FutuWatchdog, get_watchdog


def _make_watchdog():
    """构造带 mock futu_svc 的 watchdog 实例"""
    futu_svc = MagicMock()
    futu_svc.conn_mgr = MagicMock()
    futu_svc.conn_mgr.status = "DISCONNECTED"
    futu_svc.conn_mgr.quote_ctx = None
    futu_svc.conn_mgr.error_msg = ""
    return FutuWatchdog(futu_svc), futu_svc


class TestFutuWatchdog:
    """FutuWatchdog 看门狗守护进程测试套件"""

    def test_initial_state_not_running(self):
        """新实例应处于未运行状态，计数器全部为 0"""
        wd, _ = _make_watchdog()
        assert wd._running is False
        assert wd._consecutive_failures == 0
        assert wd._total_reconnects == 0
        assert wd._task is None

    def test_stop_when_not_running_is_safe(self):
        """stop 在未运行状态下应安全无操作"""
        wd, _ = _make_watchdog()
        wd.stop()
        assert wd._running is False

    def test_stop_cancels_existing_task(self):
        """stop 应取消已存在的 task"""
        wd, _ = _make_watchdog()
        fake_task = MagicMock()
        fake_task.done.return_value = False
        wd._task = fake_task
        wd._running = True
        wd.stop()
        fake_task.cancel.assert_called_once()
        assert wd._running is False

    def test_stats_returns_correct_dict(self):
        """stats 属性应返回包含所有字段的字典"""
        wd, futu_svc = _make_watchdog()
        wd._running = True
        wd._total_reconnects = 5
        wd._consecutive_failures = 2
        wd._last_reconnect_ts = 100.0
        wd._last_success_ts = 200.0
        futu_svc.conn_mgr.status = "CONNECTED"

        stats = wd.stats
        assert stats["running"] is True
        assert stats["total_reconnects"] == 5
        assert stats["consecutive_failures"] == 2
        assert stats["last_reconnect_ts"] == 100.0
        assert stats["last_success_ts"] == 200.0
        assert stats["connection_status"] == "CONNECTED"

    @pytest.mark.asyncio
    async def test_start_idempotent_skip_when_running(self):
        """已运行状态下重复调用 start 应立即返回"""
        wd, _ = _make_watchdog()
        wd._running = True
        await wd.start()  # 应立即返回
        assert wd._running is True

    @pytest.mark.asyncio
    async def test_start_loops_and_resets_running_flag_on_cancel(self):
        """start 应在收到 CancelledError 后优雅退出并重置 _running"""
        wd, futu_svc = _make_watchdog()
        # 注意：start() 内部会检查 if self._running 跳过，所以初始必须 False
        wd._running = False

        call_count = 0

        async def fake_loop():
            nonlocal call_count
            call_count += 1
            raise asyncio.CancelledError()

        with patch.object(wd, "_watchdog_loop", new=AsyncMock(side_effect=fake_loop)):
            await wd.start()

        assert call_count == 1
        assert wd._running is False

    @pytest.mark.asyncio
    async def test_start_recovers_from_unexpected_exception(self):
        """主循环异常后应休眠 5 秒，sleep 抛 CancelledError 时优雅退出"""
        wd, _ = _make_watchdog()
        wd._running = False
        attempts = []

        async def fake_loop():
            attempts.append(1)
            raise RuntimeError("unexpected")

        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            # 在 except 分支内 sleep 时抛 CancelledError，会跳过 except 继续向上传播
            # finally 块会先重置 _running=False
            raise asyncio.CancelledError()

        with (
            patch.object(wd, "_watchdog_loop", new=AsyncMock(side_effect=fake_loop)),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            try:
                await wd.start()
            except asyncio.CancelledError:
                pass  # 预期向上传播的取消信号
        assert len(attempts) == 1
        assert wd._running is False

    @pytest.mark.asyncio
    async def test_health_check_disconnected_returns_false(self):
        """status != CONNECTED 时直接返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "DISCONNECTED"
        result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_no_quote_ctx_returns_false(self):
        """status=CONNECTED 但 quote_ctx=None 时返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = None
        result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_probe_success_returns_true(self):
        """探针返回 ret=0 且非空 df 时应判定健康"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()
        futu_svc.conn_mgr.quote_ctx.get_stock_quote.return_value = (0, pd.DataFrame({"code": ["HK.00700"]}))

        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, pd.DataFrame({"code": ["HK.00700"]})))):
            result = await wd._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_probe_failure_returns_false(self):
        """探针返回非零 ret 时应判定不健康"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(-1, None))):
            result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_empty_df_returns_false(self):
        """探针返回空 DataFrame 时应判定不健康"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, pd.DataFrame()))):
            result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_none_df_returns_false(self):
        """探针返回 None df 时应判定不健康"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=(0, None))):
            result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout_returns_false(self):
        """探针超时应返回 False 而非抛出异常

        💡 修复：直接 patch _health_check 内部的 asyncio.wait_for，
        让它立即抛 TimeoutError，无需构造复杂的 Future。
        同时 cancel 未被 await 的 Future 以消除 "coroutine was never awaited"。
        """
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()

        import asyncio as _asyncio

        # 保存原始 wait_for，用于正确清理
        _orig_wait_for = _asyncio.wait_for

        async def _mocked_wait_for(coro, timeout):
            """mock wait_for：立即抛 TimeoutError"""
            # coro 是一个 Future（来自 asyncio.to_thread）
            # 必须 cancel 它，否则会被 GC 时报告 "coroutine was never awaited"
            if hasattr(coro, "cancel"):
                coro.cancel()
            raise _asyncio.TimeoutError()

        with patch("asyncio.wait_for", new=_mocked_wait_for):
            result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_exception_returns_false(self):
        """探针抛出异常时应安全返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.conn_mgr.status = "CONNECTED"
        futu_svc.conn_mgr.quote_ctx = MagicMock()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await wd._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_do_reconnect_success_returns_true(self):
        """重连流程成功且状态变为 CONNECTED 时返回 True"""
        wd, futu_svc = _make_watchdog()

        def fake_connect():
            futu_svc.conn_mgr.status = "CONNECTED"

        futu_svc.connect = fake_connect
        futu_svc.close = MagicMock()
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *a, **kw: f())):
            result = await wd._do_reconnect()
        assert result is True
        futu_svc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_do_reconnect_close_exception_resilient(self):
        """futu.close() 抛异常不应影响后续重连流程"""
        wd, futu_svc = _make_watchdog()
        futu_svc.close = MagicMock(side_effect=RuntimeError("close failed"))

        def fake_connect():
            futu_svc.conn_mgr.status = "CONNECTED"

        futu_svc.connect = fake_connect
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *a, **kw: f())):
            result = await wd._do_reconnect()
        assert result is True

    @pytest.mark.asyncio
    async def test_do_reconnect_status_not_connected_returns_false(self):
        """重连后 status 仍不是 CONNECTED 时返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.close = MagicMock()
        futu_svc.conn_mgr.status = "ERROR"
        futu_svc.conn_mgr.error_msg = "OpenD unreachable"

        def fake_connect():
            pass  # 不修改 status

        futu_svc.connect = fake_connect
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=lambda f, *a, **kw: f())):
            result = await wd._do_reconnect()
        assert result is False

    @pytest.mark.asyncio
    async def test_do_reconnect_timeout_returns_false(self):
        """重连超时应返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.close = MagicMock()
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await wd._do_reconnect()
        assert result is False

    @pytest.mark.asyncio
    async def test_do_reconnect_unexpected_exception_returns_false(self):
        """重连过程中出现未预期异常应返回 False"""
        wd, futu_svc = _make_watchdog()
        futu_svc.close = MagicMock()
        with patch("asyncio.wait_for", side_effect=RuntimeError("unexpected")):
            result = await wd._do_reconnect()
        assert result is False

    @pytest.mark.asyncio
    async def test_watchdog_loop_healthy_path_resets_counters(self):
        """健康路径应重置 consecutive_failures 并休眠 HEALTH_CHECK_INTERVAL"""
        wd, futu_svc = _make_watchdog()
        wd._consecutive_failures = 3
        wd._running = True
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            wd._running = False  # 退出循环

        with (
            patch.object(wd, "_health_check", new=AsyncMock(return_value=True)),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await wd._watchdog_loop()
        assert wd._consecutive_failures == 0
        assert sleep_calls == [wd.HEALTH_CHECK_INTERVAL]

    @pytest.mark.asyncio
    async def test_watchdog_loop_unhealthy_triggers_reconnect(self):
        """不健康路径应递增计数器并调用 _do_reconnect"""
        wd, futu_svc = _make_watchdog()
        wd._running = True
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            wd._running = False

        with (
            patch.object(wd, "_health_check", new=AsyncMock(return_value=False)),
            patch.object(wd, "_do_reconnect", new=AsyncMock(return_value=True)),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await wd._watchdog_loop()
        assert wd._consecutive_failures == 1
        assert wd._total_reconnects == 1
        # sleep 应包含两段：退避延迟 + HEALTH_CHECK_INTERVAL 之前实际上没有
        # 因为 _running=False 后立即 break，不进入下次 _health_check
        assert len(sleep_calls) == 1  # 只调用了退避 sleep

    @pytest.mark.asyncio
    async def test_watchdog_loop_long_sleep_when_max_failures(self):
        """连续失败 >= MAX_CONSECUTIVE_FAILURES 时应使用 LONG_SLEEP"""
        wd, _ = _make_watchdog()
        wd._running = True
        # 预设计数器接近阈值
        wd._consecutive_failures = wd.MAX_CONSECUTIVE_FAILURES - 1
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            wd._running = False

        with (
            patch.object(wd, "_health_check", new=AsyncMock(return_value=False)),
            patch.object(wd, "_do_reconnect", new=AsyncMock(return_value=False)),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await wd._watchdog_loop()
        # consecutive_failures 现在达到阈值，sleep 应是 LONG_SLEEP
        assert wd._consecutive_failures == wd.MAX_CONSECUTIVE_FAILURES
        assert sleep_calls[0] == wd.LONG_SLEEP

    @pytest.mark.asyncio
    async def test_watchdog_loop_reconnect_failure_increments_failure_metric(self):
        """重连失败时不递增 consecutive_failures（仅在健康检查失败时递增）"""
        wd, _ = _make_watchdog()
        wd._running = True
        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            wd._running = False

        with (
            patch.object(wd, "_health_check", new=AsyncMock(return_value=False)),
            patch.object(wd, "_do_reconnect", new=AsyncMock(return_value=False)),
            patch("asyncio.sleep", new=fake_sleep),
        ):
            await wd._watchdog_loop()
        # _health_check 失败一次 -> consecutive_failures=1
        # _do_reconnect 失败但不会再次递增
        assert wd._consecutive_failures == 1


def test_get_watchdog_singleton(monkeypatch):
    """get_watchdog 应返回全局单例"""
    import backend.services.futu.watchdog as wd_module

    monkeypatch.setattr(wd_module, "_watchdog", None)
    futu_svc = MagicMock()
    futu_svc.conn_mgr = MagicMock()
    wd1 = get_watchdog(futu_svc)
    wd2 = get_watchdog(futu_svc)
    assert wd1 is wd2
    # 清理全局状态
    monkeypatch.setattr(wd_module, "_watchdog", None)
