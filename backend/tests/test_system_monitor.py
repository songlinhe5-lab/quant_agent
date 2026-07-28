"""单测：workers/monitor/system_monitor.SystemMonitorService

覆盖：性能日志落库（正常写入 / 异常不向上抛）、事件循环卡顿监控守护进程
（模拟卡顿触发告警、短窗口去抖只告警一次、无卡顿不告警）。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.workers.monitor import system_monitor
from backend.workers.monitor.system_monitor import SystemMonitorService


def test_save_performance_log_writes_db(monkeypatch):
    svc = SystemMonitorService()
    db = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False
    mock_sl = MagicMock(return_value=cm)
    monkeypatch.setattr(system_monitor, "SessionLocal", mock_sl)

    svc._save_performance_log("event_loop_block", 900.0, None, "卡顿延迟: 900 ms")

    db.add.assert_called_once()
    db.commit.assert_called_once()
    # 写入对象应为 PerformanceLog 实例
    assert db.add.call_args.args[0].__class__.__name__ == "PerformanceLog"


def test_save_performance_log_swallows_db_exception(monkeypatch):
    svc = SystemMonitorService()
    db = MagicMock()
    db.commit.side_effect = Exception("db connection lost")
    cm = MagicMock()
    cm.__enter__.return_value = db
    cm.__exit__.return_value = False
    monkeypatch.setattr(system_monitor, "SessionLocal", MagicMock(return_value=cm))

    # 不应向调用方抛出异常
    svc._save_performance_log("event_loop_block", 900.0, None, "卡顿延迟: 900 ms")
    db.add.assert_called_once()


async def _drive_daemon(svc, n_iterations, block, clock_start=1000.0):
    """驱动 event_loop_monitor_daemon 跑 n_iterations 次后通过 CancelledError 退出。"""
    seq = []
    for k in range(n_iterations):
        seq.append(float(k))
        seq.append(float(k) + (1.0 if block else 0.0))
    perf_iter = iter(seq)

    def fake_perf():
        try:
            return next(perf_iter)
        except StopIteration:
            return float(n_iterations)

    clock_state = {"calls": 0}

    def fake_time():
        v = clock_start + clock_state["calls"] * 10.0
        clock_state["calls"] += 1
        return v

    sleep_state = {"n": 0}

    async def fake_sleep(interval):
        sleep_state["n"] += 1
        if sleep_state["n"] > n_iterations:
            raise asyncio.CancelledError()

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(system_monitor.time, "perf_counter", fake_perf)
        mp.setattr(system_monitor.time, "time", fake_time)
        # create_task 置空，避免测试残留未 awaited 的协程
        mp.setattr(system_monitor.asyncio, "create_task", lambda coro: None)
        mp.setattr(system_monitor.asyncio, "sleep", fake_sleep)
        await svc.event_loop_monitor_daemon()


async def test_event_loop_block_triggers_alert(monkeypatch):
    svc = SystemMonitorService()
    alert = AsyncMock()
    # 守护进程使用模块级单例 notification_service，需直接 patch
    monkeypatch.setattr(system_monitor, "notification_service", MagicMock(send_alert=alert))

    await _drive_daemon(svc, n_iterations=1, block=True)

    alert.assert_called_once()
    assert svc._last_alert_time > 0


async def test_event_loop_block_debounced(monkeypatch):
    svc = SystemMonitorService()
    alert = AsyncMock()
    monkeypatch.setattr(system_monitor, "notification_service", MagicMock(send_alert=alert))

    # 两次卡顿间隔 10s (< 60s 去抖窗口) -> 仅告警一次
    await _drive_daemon(svc, n_iterations=2, block=True)

    alert.assert_called_once()


async def test_no_block_no_alert(monkeypatch):
    svc = SystemMonitorService()
    alert = AsyncMock()
    monkeypatch.setattr(system_monitor, "notification_service", MagicMock(send_alert=alert))

    await _drive_daemon(svc, n_iterations=1, block=False)

    alert.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
