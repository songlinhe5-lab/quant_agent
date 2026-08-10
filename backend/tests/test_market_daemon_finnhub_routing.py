"""Finnhub 远程路由测试（替换旧 test_finnhub_service_daemon）。

架构背景（BE-ARCH-01 / SVC-06，2026-08-07）：
- Finnhub 连接层（REST + WS）已下沉 data_subservice（_internal/finnhub + finnhub_worker.py）。
- 主服务 market/daemon.py 经 datasource_registry.fetch("finnhub", action, params)
  远程取数，不再持有 FinnhubService 实例、不再维护 WS 订阅。
- 本测试验证 daemon 层所有 Finnhub 相关路径均走「远程 fetch」，并对失败/降级分支做断言。

注：原 FinnhubService._get_proxy 已迁移至 backend.core.yahoo_news，相关用例见
test_core_yahoo_news.py。
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.services.datasource import Result, ResultStatus
from backend.workers.market import daemon as md


def _result(data):
    return Result(status=ResultStatus.SUCCESS, data=data)


class FakeLLM:
    """极简 LLM 桩：让财报/新闻 daemon 的 AI 解读分支可单测。"""

    def get_client(self):
        return self

    def get_model(self):
        return "gpt-test"

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        msg = type("M", (), {"content": "beat"})()
        choice = type("C", (), {"message": msg})()
        return type("R", (), {"choices": [choice]})()


@pytest.mark.asyncio
async def test_finnhub_fetch_maps_action_and_params():
    captured = {}

    async def fake_fetch(source, action, params):
        captured.update({"source": source, "action": action, "params": params})
        return _result({"ok": True})

    with pytest.MonkeyPatch().context() as m:
        m.setattr(md.datasource_registry, "fetch", fake_fetch)
        out = await md._finnhub_fetch("company_news", ticker="AAPL", days_back=3)

    assert out == {"ok": True}
    assert captured["source"] == "finnhub"
    assert captured["action"] == "company_news"
    assert captured["params"] == {"ticker": "AAPL", "days_back": 3}


@pytest.mark.asyncio
async def test_finnhub_fetch_returns_none_on_failure():
    async def fake_fetch(source, action, params):
        return Result(is_success=False, error="remote down", status_code=503)

    with pytest.MonkeyPatch().context() as m:
        m.setattr(md.datasource_registry, "fetch", fake_fetch)
        assert await md._finnhub_fetch("company_news", ticker="AAPL") is None


class _DaemonStop(Exception):
    """测试用哨兵：让无限 while True 的 daemon 在跑过一次循环体后干净退出。"""


def _make_sleep_that_stops_after_first():
    """mock asyncio.sleep：第一次调用放行（让循环体执行一次），第二次 raise 终止 daemon。"""
    state = {"n": 0}

    async def _fake_sleep(*args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return None
        raise _DaemonStop()

    return _fake_sleep


class FakeRedis:
    """隔离真实 Redis 的桩：daemon 仅需 set/zadd/publish 等异步方法。"""

    async def set(self, *args, **kwargs):
        return True

    async def zadd(self, *args, **kwargs):
        return 1

    async def publish(self, *args, **kwargs):
        return 1

    async def hkeys(self, *args, **kwargs):
        return []

    async def zremrangebyscore(self, *args, **kwargs):
        return 0

    async def zremrangebyrank(self, *args, **kwargs):
        return 0


@pytest.mark.asyncio
async def test_earnings_alert_daemon_remote_path(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    sent = []

    class FakeNotify:
        async def send_alert(self, msg):
            sent.append(msg)

    earnings = [
        {
            "symbol": "AAPL",
            "date": "2099-01-01",
            "epsActual": 2.0,
            "epsEstimate": 1.0,
            "revenueActual": 1.2e11,
            "revenueEstimate": 1.0e11,
            "quarter": "Q1",
        }
    ]

    import backend.services.ai_narrator.llm_service as llm_mod
    import backend.services.alert.notification as notif_mod

    with pytest.MonkeyPatch().context() as m:
        m.setattr("asyncio.sleep", _make_sleep_that_stops_after_first())
        m.setattr(md, "redis_client", FakeRedis())
        m.setattr(notif_mod, "notification_service", FakeNotify())
        m.setattr(llm_mod, "llm_service", FakeLLM())
        m.setattr(md, "_finnhub_fetch", AsyncMock(return_value=earnings))

        # daemon 无限循环：跑过一次循环体（发 alert）后由 fake_sleep 终止，干净退出。
        task = asyncio.ensure_future(md._earnings_alert_daemon())
        with pytest.raises(_DaemonStop):
            await task

    assert len(sent) >= 1


@pytest.mark.asyncio
async def test_news_stream_daemon_exits_without_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    await asyncio.wait_for(md._news_stream_daemon(), timeout=2.0)


@pytest.mark.asyncio
async def test_daemon_skips_when_registry_fetch_none(monkeypatch):
    """_finnhub_fetch 返回 None（远程不可达）时，daemon 不抛异常、不通知。"""
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    sent = []

    class FakeNotify:
        async def send_alert(self, msg):
            sent.append(msg)

    import backend.services.ai_narrator.llm_service as llm_mod
    import backend.services.alert.notification as notif_mod

    with pytest.MonkeyPatch().context() as m:
        m.setattr("asyncio.sleep", _make_sleep_that_stops_after_first())
        m.setattr(md, "redis_client", FakeRedis())
        m.setattr(notif_mod, "notification_service", FakeNotify())
        m.setattr(llm_mod, "llm_service", FakeLLM())
        m.setattr(md, "_finnhub_fetch", AsyncMock(return_value=None))

        task = asyncio.ensure_future(md._earnings_alert_daemon())
        with pytest.raises(_DaemonStop):
            await task

    assert sent == []


def test_no_finnhub_service_import_in_daemon():
    import inspect

    src = inspect.getsource(md)
    assert "from backend.services.finnhub.service import" not in src
    assert "finnhub_service" not in src.split("Finnhub")[0] if "Finnhub" in src else True
