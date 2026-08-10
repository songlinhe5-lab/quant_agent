"""
SVC-05: 配额与成本监控器单元测试。

验证：
1. TokenUsageStore.record / get_today（Redis 不可用时走内存降级）
2. LLM 预算消耗达 80% → warning；达 100% → critical
3. 未启用预算（budget=0）→ 不告警
4. Finnhub 当日配额耗尽 → critical 告警
5. 去重冷却：同类型 15min 内不重复告警
6. is_healthy() 在 start/stop 生命周期内的正确性
7. 端到端：扫描触发 → 队列 → consumer 经 NotificationService 推送飞书
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai_narrator.quota_monitor import QuotaCostMonitor, quota_cost_monitor
from backend.services.ai_narrator.token_usage_store import TokenUsageStore


# ── TokenUsageStore ─────────────────────────────────────
@pytest.fixture
def broken_redis(monkeypatch):
    """让 token_usage_store 的 redis_client 全部抛异常 → 走内存降级路径。"""
    import backend.services.ai_narrator.token_usage_store as tus

    fake = MagicMock()
    fake.hgetall = AsyncMock(side_effect=RuntimeError("no redis"))
    pipe = MagicMock()
    pipe.hincrby = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(side_effect=RuntimeError("no redis"))
    fake.pipeline = MagicMock(return_value=pipe)
    monkeypatch.setattr(tus, "redis_client", fake)
    return fake


async def test_token_store_record_and_get_today(broken_redis):
    """record 后内存累计正确，get_today 返回降级值。"""
    store = TokenUsageStore(enabled=True)
    await store.record(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    await store.record(prompt_tokens=20, completion_tokens=10, total_tokens=30)

    today = await store.get_today()
    assert today["prompt_tokens"] == 30
    assert today["completion_tokens"] == 15
    assert today["total_tokens"] == 45
    assert today["calls"] == 2
    assert today["metric_source"] == "memory_fallback"


async def test_token_store_disabled(broken_redis):
    """disabled 时 record 不累计，get_today 返回全 0。"""
    store = TokenUsageStore(enabled=False)
    await store.record(prompt_tokens=10)
    today = await store.get_today()
    assert today["total_tokens"] == 0
    assert today["metric_source"] == "disabled"


# ── QuotaCostMonitor ────────────────────────────────────
@pytest.fixture
def monitor():
    m = QuotaCostMonitor(scan_interval=1, llm_daily_budget=1000)
    yield m
    m.reset()


def _token_store_stub(total_tokens: int, calls: int = 1):
    store = MagicMock()
    store.get_today = AsyncMock(
        return_value={
            "date": "2026-08-09",
            "metric_source": "redis",
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": total_tokens,
            "calls": calls,
        }
    )
    return store


def _call_metrics_stub(finnhub_metrics=None):
    cm = MagicMock()
    cm.get_today = AsyncMock(side_effect=lambda name: finnhub_metrics if name == "finnhub" else None)
    return cm


async def test_llm_budget_warning(monitor):
    """消耗 850/1000 = 85% (≥80% 且 <100%) → warning。"""
    monitor._get_token_store = lambda: _token_store_stub(850)
    monitor._get_call_metrics = lambda: _call_metrics_stub(None)
    alerts = await monitor._scan_once()
    assert len(alerts) == 1
    assert alerts[0].alert_type == "llm_token_budget"
    assert alerts[0].severity == "warning"
    assert "85%" in alerts[0].message


async def test_llm_budget_critical(monitor):
    """消耗 1000/1000 = 100% (≥100%) → critical。"""
    monitor._get_token_store = lambda: _token_store_stub(1000)
    monitor._get_call_metrics = lambda: _call_metrics_stub(None)
    alerts = await monitor._scan_once()
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"
    assert "耗尽" in alerts[0].message


async def test_llm_budget_no_alert_below_threshold(monitor):
    """消耗 500/1000 = 50% (<80%) → 不告警。"""
    monitor._get_token_store = lambda: _token_store_stub(500)
    monitor._get_call_metrics = lambda: _call_metrics_stub(None)
    alerts = await monitor._scan_once()
    assert alerts == []


async def test_budget_disabled_no_alert():
    """未启用预算 (budget=0) → 即使消耗再高也不告警。"""
    m = QuotaCostMonitor(scan_interval=1, llm_daily_budget=0)
    m._get_token_store = lambda: _token_store_stub(999999)
    m._get_call_metrics = lambda: _call_metrics_stub(None)
    alerts = await m._scan_once()
    assert alerts == []


async def test_finnhub_quota_exhausted(monitor):
    """Finnhub 当日 quota_exhausted=3 → critical 告警。"""
    finnhub = {
        "source": "finnhub",
        "calls": 100,
        "success_rate": 0.9,
        "rl_breakdown": {"rate_limit": 0, "quota_exhausted": 3, "ip_blocked": 0},
    }
    monitor._get_token_store = lambda: _token_store_stub(100)  # 未触预算
    monitor._get_call_metrics = lambda: _call_metrics_stub(finnhub)
    alerts = await monitor._scan_once()
    assert len(alerts) == 1
    assert alerts[0].alert_type == "finnhub_quota_exhausted"
    assert alerts[0].severity == "critical"


async def test_finnhub_quota_ok_no_alert(monitor):
    """Finnhub 配额未耗尽 → 不告警。"""
    finnhub = {
        "source": "finnhub",
        "calls": 100,
        "success_rate": 0.95,
        "rl_breakdown": {"rate_limit": 0, "quota_exhausted": 0, "ip_blocked": 0},
    }
    monitor._get_token_store = lambda: _token_store_stub(100)
    monitor._get_call_metrics = lambda: _call_metrics_stub(finnhub)
    alerts = await monitor._scan_once()
    assert alerts == []


async def test_dedup_cooldown(monitor):
    """同类型冷却期内不重复创建告警。"""
    monitor._get_token_store = lambda: _token_store_stub(1000)
    monitor._get_call_metrics = lambda: _call_metrics_stub(None)
    a1 = monitor._try_create_alert("llm", "llm_token_budget", "critical", "m1")
    a2 = monitor._try_create_alert("llm", "llm_token_budget", "critical", "m2")
    assert a1 is not None
    assert a2 is None


async def test_combined_alerts(monitor):
    """LLM 预算 + Finnhub 配额同时触发 → 两条告警。"""
    finnhub = {
        "source": "finnhub",
        "calls": 100,
        "success_rate": 0.9,
        "rl_breakdown": {"rate_limit": 0, "quota_exhausted": 1, "ip_blocked": 0},
    }
    monitor._get_token_store = lambda: _token_store_stub(1000)
    monitor._get_call_metrics = lambda: _call_metrics_stub(finnhub)
    alerts = await monitor._scan_once()
    assert len(alerts) == 2
    types = {a.alert_type for a in alerts}
    assert "llm_token_budget" in types
    assert "finnhub_quota_exhausted" in types


async def test_is_healthy_lifecycle(monitor):
    """start 后 is_healthy=True，stop 后 False。"""
    assert monitor.is_healthy() is False
    await monitor.start()
    assert monitor.is_healthy() is True
    await monitor.stop()
    assert monitor.is_healthy() is False


async def test_scan_loop_enqueues_and_consumes(monitor):
    """端到端：扫描触发告警 → 队列 → consumer 经 NotificationService 推送飞书。"""
    monitor._get_token_store = lambda: _token_store_stub(1000)
    monitor._get_call_metrics = lambda: _call_metrics_stub(None)

    sent = []

    class FakeNotify:
        async def send_alert(self, message, priority="P2", source="system"):
            sent.append((message, priority, source))

    monitor._get_notification_service = lambda: FakeNotify()

    await monitor.start()
    await asyncio.sleep(2.5)
    await monitor.stop()

    assert len(sent) >= 1, "告警应经 NotificationService 推送到飞书"
    assert "LLM" in sent[0][0]
    assert sent[0][2] == "quota:llm_token_budget"


def test_singleton_exists():
    assert quota_cost_monitor is not None
    assert isinstance(quota_cost_monitor, QuotaCostMonitor)
