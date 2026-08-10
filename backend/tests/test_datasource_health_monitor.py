"""
SVC-03: 数据源健康告警监控器单元测试。

验证：
1. 成功率 < 阈值 (95%) 且样本充足 → 触发 low_success_rate 告警
2. 调用量 < 最小样本 → 不误报
3. 去重冷却：同源同类型 15min 内不重复告警
4. is_healthy() 在 start/stop 生命周期内的正确性
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.services.datasource.health_monitor import (
    DataSourceHealthMonitor,
    data_source_health_monitor,
)


@pytest.fixture
def monitor():
    m = DataSourceHealthMonitor(scan_interval=1, success_rate_threshold=0.95, min_samples=20)
    yield m
    m.reset()


def _registry_stub(names, mounted_map):
    reg = MagicMock()
    reg.list_names.return_value = names
    reg.has.side_effect = lambda n: mounted_map.get(n, False)
    return reg


def _metrics_stub(metrics_by_source: dict):
    cm = MagicMock()
    cm.get_today.side_effect = lambda name: metrics_by_source.get(name)
    return cm


async def test_low_success_rate_triggers_alert(monitor):
    """成功率 0.75 (<0.8, 远低于 0.95) 且样本 100 → 触发 critical 告警。"""
    metrics = {
        "finnhub": {
            "source": "finnhub",
            "calls": 100,
            "success_rate": 0.75,
        }
    }
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    alerts = await monitor._scan_once()
    assert len(alerts) == 1
    assert alerts[0].alert_type == "low_success_rate"
    assert alerts[0].severity == "critical"
    assert "finnhub" in alerts[0].message


async def test_healthy_rate_no_alert(monitor):
    """成功率 0.98 (>0.95) → 不告警。"""
    metrics = {"finnhub": {"source": "finnhub", "calls": 100, "success_rate": 0.98}}
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    alerts = await monitor._scan_once()
    assert alerts == []


async def test_low_sample_no_false_positive(monitor):
    """样本 10 (< min_samples 20) 即使成功率 0.50 也不告警（防低流量误报）。"""
    metrics = {"finnhub": {"source": "finnhub", "calls": 10, "success_rate": 0.50}}
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    alerts = await monitor._scan_once()
    assert alerts == []


async def test_dedup_cooldown(monitor):
    """同数据源同类型冷却期内不重复创建告警。"""
    metrics = {"finnhub": {"source": "finnhub", "calls": 100, "success_rate": 0.80}}
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    a1 = monitor._try_create_alert("finnhub", "low_success_rate", "critical", "m1")
    a2 = monitor._try_create_alert("finnhub", "low_success_rate", "critical", "m2")
    assert a1 is not None
    assert a2 is None  # 冷却期内被去重


async def test_warning_severity_for_moderate_drop(monitor):
    """成功率 0.90（仅略低于 0.95 但 >0.80）→ warning 级别。"""
    metrics = {"finnhub": {"source": "finnhub", "calls": 100, "success_rate": 0.90}}
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    alerts = await monitor._scan_once()
    assert len(alerts) == 1
    assert alerts[0].severity == "warning"


async def test_is_healthy_lifecycle(monitor):
    """start 后 is_healthy=True，stop 后 False。"""
    assert monitor.is_healthy() is False
    await monitor.start()
    assert monitor.is_healthy() is True
    await monitor.stop()
    assert monitor.is_healthy() is False


async def test_scan_loop_enqueues_and_consumes(monitor):
    """端到端：扫描触发告警 → 队列 → consumer 经 NotificationService 推送飞书。"""

    metrics = {"finnhub": {"source": "finnhub", "calls": 100, "success_rate": 0.70}}
    monitor._get_call_metrics = lambda: _metrics_stub(metrics)
    monitor._get_registry = lambda: _registry_stub(["finnhub"], {"finnhub": True})

    sent = []

    class FakeNotify:
        async def send_alert(self, message, priority="P2", source="system"):
            sent.append((message, priority, source))

    monitor._get_notification_service = lambda: FakeNotify()

    await monitor.start()
    # 等待至少一次扫描周期（scan_interval=1s）+ consumer 处理
    await asyncio.sleep(2.5)
    await monitor.stop()

    assert len(sent) >= 1, "告警应经 NotificationService 推送到飞书"
    assert "finnhub" in sent[0][0]
    assert sent[0][2] == "datasource:finnhub"


def test_singleton_exists():
    assert data_source_health_monitor is not None
    assert isinstance(data_source_health_monitor, DataSourceHealthMonitor)
