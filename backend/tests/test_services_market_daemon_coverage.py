"""market/daemon.py 覆盖测试（SVC-06 市场化推送，全远程架构）。

覆盖：
1. _finnhub_fetch 经 datasource_registry.fetch("finnhub", ...) 远程路由（BE-ARCH-01/05）。
2. _earnings_alert_daemon 经远程 fetch 取数并触发通知（一次迭代 + 超时取消）。
3. _news_stream_daemon 在「未配置 FINNHUB_API_KEY」时静默退出（能力探测保护）。
4. run_global_daemon 聚合正确的子 daemon。
5. 架构约束：_trade_stream_daemon(WS) 已移除，不再直连 FinnhubService。

注意：daemon 内部多为 while True 轮询，单测用 asyncio.wait_for 触发一次迭代后
强制取消，避免挂起。
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


@pytest.mark.asyncio
async def test_finnhub_fetch_routes_to_registry():
    captured = {}

    async def fake_fetch(source, action, params):
        captured.update({"source": source, "action": action, "params": params})
        return _result([{"headline": "x"}])

    with pytest.MonkeyPatch().context() as m:
        m.setattr(md.datasource_registry, "fetch", fake_fetch)
        out = await md._finnhub_fetch("company_news", ticker="AAPL", days_back=3)

    assert out == [{"headline": "x"}]
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


@pytest.mark.asyncio
async def test_finnhub_fetch_returns_none_on_exception():
    async def fake_fetch(source, action, params):
        raise RuntimeError("boom")

    with pytest.MonkeyPatch().context() as m:
        m.setattr(md.datasource_registry, "fetch", fake_fetch)
        assert await md._finnhub_fetch("company_news", ticker="AAPL") is None


@pytest.mark.asyncio
async def test_earnings_alert_daemon_triggers_notification(monkeypatch):
    """设 FINNHUB_API_KEY，mock 远程 fetch 返回核心股财报，验证通知被调用一次。

    notification_service / llm_service 是 _earnings_alert_daemon 函数内局部导入，
    需 patch 源模块属性（BE-ARCH-01 边界：不直接持有 FinnhubService 实例）。
    """
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
    from backend.core.redis_client import redis_client as rc

    with pytest.MonkeyPatch().context() as m:
        m.setattr("asyncio.sleep", _make_sleep_that_stops_after_first())
        m.setattr(notif_mod, "notification_service", FakeNotify())
        m.setattr(llm_mod, "llm_service", FakeLLM())
        m.setattr(rc, "set", AsyncMock(return_value=True))
        m.setattr(md, "_finnhub_fetch", AsyncMock(return_value=earnings))

        task = asyncio.ensure_future(md._earnings_alert_daemon())
        try:
            await task
        except _DaemonStop:
            pass  # 哨兵：daemon 跑过一次循环体后干净退出

    assert len(sent) == 1
    assert "AAPL" in sent[0]


@pytest.mark.asyncio
async def test_news_stream_daemon_skips_without_api_key(monkeypatch):
    """未配置 FINNHUB_API_KEY 时，_news_stream_daemon 直接 return（能力探测保护）。"""
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    # 应直接返回，不进入轮询循环
    await asyncio.wait_for(md._news_stream_daemon(), timeout=2.0)


@pytest.mark.asyncio
async def test_run_global_daemon_aggregates_subdaemons(monkeypatch):
    """验证 run_global_daemon 聚合了指定的 5 个子 daemon（mock 为立即返回）。"""
    started = []

    async def fake_daemon():
        started.append(True)

    with pytest.MonkeyPatch().context() as m:
        m.setattr(md, "_news_stream_daemon", fake_daemon)
        m.setattr(md, "_company_news_daemon", fake_daemon)
        m.setattr(md, "macro_alert_daemon", fake_daemon)
        m.setattr(md, "_insider_transactions_marquee_daemon", fake_daemon)
        m.setattr(md, "_earnings_alert_daemon", fake_daemon)

        await asyncio.wait_for(md.run_global_daemon(), timeout=2.0)

    assert len(started) == 5


def test_no_websocket_subscription_in_daemon():
    """架构约束：market daemon 不得再创建 WS 订阅（subscribe_company_news / _trade_stream_daemon）。"""
    assert not hasattr(md, "_trade_stream_daemon")
    import inspect

    src = inspect.getsource(md._news_stream_daemon) + inspect.getsource(md._company_news_daemon)
    assert "subscribe_company_news" not in src
    assert "WebSocket" not in src
    # 不得残留对 FinnhubService 的本地方法调用
    assert "finnhub_service" not in inspect.getsource(md)
