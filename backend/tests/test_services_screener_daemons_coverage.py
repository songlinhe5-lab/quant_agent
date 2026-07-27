"""补充 services/screener/daemons.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行 (27-226, 228-342, 344-408):
- 三个后台守护进程的循环体, 通过 monkeypatch datetime.now 到触发时刻 +
  '第二次 asyncio.sleep 抛 _BreakLoop' 跳出 while True + 拦截 asyncio.to_thread
  注入假订阅 / 屏蔽 DB 副作用 + mock futu/llm/notification/redis。
- 具体覆盖: 订阅守护 (到达触发 -> 分布式锁 -> DSL 解析 -> 扫盘 -> 大模型点评 ->
  推送, 27-226) / 每日强势股盘点 (16:00, 228-342) / 知识库 TTL 清理 (00:00, 344-408)。
"""

import asyncio
import json
from datetime import datetime as _dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.screener import daemons as sd
from backend.services.screener.daemons import DaemonMixin


class _BreakLoop(Exception):
    pass


def _make_sleep_breaker(monkeypatch):
    state = {"n": 0}

    async def _break(*a, **k):
        state["n"] += 1
        if state["n"] >= 2:
            raise _BreakLoop()

    monkeypatch.setattr(asyncio, "sleep", _break)


class DummyDaemon(DaemonMixin):
    def parse_dsl_to_futu_filters(self, dsl):
        return (["US"], {}, {})

    async def apply_technical_pattern_filtering(self, data, patterns):
        return data


def _fix_now(monkeypatch, hour, minute):
    fixed = _dt(2024, 1, 1, hour, minute, 0)

    class _FakeDateTime:
        @staticmethod
        def now():
            return fixed

    monkeypatch.setattr(sd, "datetime", _FakeDateTime)


def _patch_to_thread(monkeypatch, subs):
    orig = asyncio.to_thread

    def _fake(fn, *a, **k):
        if getattr(fn, "__name__", "") == "_fetch_due_subscriptions":
            return subs
        if getattr(fn, "__name__", "") == "_mark_triggered":
            return None
        return orig(fn, *a, **k)

    monkeypatch.setattr(asyncio, "to_thread", _fake)


# ── 订阅守护进程 (27-226) ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_screener_subscription_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)
    _fix_now(monkeypatch, 18, 0)
    subs = [
        {
            "id": "sub1",
            "name": "test-sub",
            "dsl": json.dumps({"markets": ["US"]}),
            "last_triggered_at": None,
        }
    ]
    _patch_to_thread(monkeypatch, subs)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)

    futu = MagicMock()
    futu.screen_stocks = AsyncMock(
        return_value={"status": "success", "data": [{"symbol": "AAPL", "name": "Apple", "change_rate": 1.0}]}
    )
    llm_client = MagicMock()
    llm_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="强者恒强"))])
    )
    llm = MagicMock()
    llm.get_client = lambda: llm_client
    llm.get_model = lambda: "gpt"
    notify = MagicMock()
    notify.send_alert = AsyncMock()

    finnhub = MagicMock()
    finnhub.get_company_news = AsyncMock(return_value={"status": "success", "data": [{"headline": "good"}]})

    with (
        patch.object(sd, "redis_client", redis),
        patch.object(sd, "futu_service", futu),
        patch.object(sd, "llm_service", llm),
        patch.object(sd, "notification_service", notify),
        patch("backend.services.finnhub_service.finnhub_service", finnhub),
    ):
        daemon = DummyDaemon()
        with pytest.raises(_BreakLoop):
            await daemon.screener_subscription_daemon()


# ── 每日强势股盘点 (228-342) ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_daily_market_summary_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)
    _fix_now(monkeypatch, 16, 0)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)

    futu = MagicMock()
    futu.screen_stocks = AsyncMock(
        return_value={
            "status": "success",
            "data": [{"symbol": "AAPL", "name": "Apple", "change_rate": 1.0, "turnover_rate": 2.0, "turnover": 1e8}],
        }
    )
    llm_client = MagicMock()
    llm_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="主线清晰"))])
    )
    llm = MagicMock()
    llm.get_client = lambda: llm_client
    llm.get_model = lambda: "gpt"
    notify = MagicMock()
    notify.send_alert = AsyncMock()

    with (
        patch.object(sd, "redis_client", redis),
        patch.object(sd, "futu_service", futu),
        patch.object(sd, "llm_service", llm),
        patch.object(sd, "notification_service", notify),
    ):
        daemon = DummyDaemon()
        with pytest.raises(_BreakLoop):
            await daemon.daily_market_summary_daemon()


# ── 知识库 TTL 清理 (344-408) ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_clean_obsolete_knowledge_base_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)
    _fix_now(monkeypatch, 0, 0)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)

    class _FakeConn:
        def execute(self, *a, **k):
            res = MagicMock()
            res.scalar = lambda: True
            res.rowcount = 0
            return res

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _FakeEngine:
        def begin(self):
            return _FakeConn()

    with patch.object(sd, "redis_client", redis), patch.object(sd, "engine", _FakeEngine()):
        daemon = DummyDaemon()
        with pytest.raises(_BreakLoop):
            await daemon.clean_obsolete_knowledge_base_daemon()
