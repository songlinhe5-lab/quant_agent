"""补充 services/market_daemon.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行:
- _generate_news_tags 纯函数 (584-593)
- _get_news_tags_rules: 命中缓存 / 走默认规则 (561-581)
- 各守护进程主体 (299-381, 407-479, 505-555, 184-206) 采用 "第二次 asyncio.sleep 抛
  出 _BreakLoop 跳出 while True" 模式, 配合 mock 外部服务一次性跑通循环体。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services import market_daemon as md


class _BreakLoop(Exception):
    """用于打断 daemon 的 while True 循环。"""


def _make_sleep_breaker(monkeypatch):
    state = {"n": 0}

    async def _break(*a, **k):
        state["n"] += 1
        if state["n"] >= 2:
            raise _BreakLoop()

    monkeypatch.setattr(asyncio, "sleep", _break)


# ── 纯函数 (584-593) ──────────────────────────────────────────────────────────
def test_generate_news_tags():
    rules = {
        "FED": r"\b(fed|fomc)\b",
        "INFLATION": r"\b(cpi|pce)\b",
        "BAD": r"([unclosed",  # 非法正则 -> re.error -> 跳过
    }
    tags = md._generate_news_tags("fed cuts rates as cpi cools", rules)
    assert "FED" in tags
    assert "INFLATION" in tags
    assert "BAD" not in tags  # 非法正则被跳过


# ── _get_news_tags_rules (561-581) ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_news_tags_rules_cached():
    fake = AsyncMock()
    fake.get = AsyncMock(return_value='{"CUSTOM": "x"}')
    with patch.object(md, "l1_cached_redis", fake):
        rules = await md._get_news_tags_rules()
    assert rules == {"CUSTOM": "x"}


@pytest.mark.asyncio
async def test_get_news_tags_rules_default():
    fake = AsyncMock()
    fake.get = AsyncMock(return_value=None)
    with patch.object(md, "l1_cached_redis", fake):
        rules = await md._get_news_tags_rules()
    assert "FED" in rules  # 回退到默认规则


# ── _earnings_alert_daemon (299-381) ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_earnings_alert_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    finnhub = MagicMock()
    finnhub.get_earnings_calendar = AsyncMock(
        return_value=[
            {
                "symbol": "AAPL",
                "period": "2024Q1",
                "date": "2024-01-01",
                "eps_estimate": 1.0,
                "eps_actual": 1.2,
                "revenue_estimate": 100,
                "revenue_actual": 110,
            }
        ]
    )

    llm_client = MagicMock()
    llm_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="超预期"))])
    )
    llm = MagicMock()
    llm.get_client = lambda: llm_client
    llm.get_model = lambda: "gpt"

    notify = MagicMock()
    notify.send_alert = AsyncMock()

    redis = MagicMock()
    redis.set = AsyncMock(side_effect=[True, False])  # is_new 命中与跳过两条分支
    redis.zadd = AsyncMock()

    with (
        patch.object(md, "redis_client", redis),
        patch("backend.services.llm_service.llm_service", llm),
        patch("backend.services.notification_service.notification_service", notify),
    ):
        with pytest.raises(_BreakLoop):
            await md._earnings_alert_daemon(finnhub)


# ── _macro_alert_daemon (407-479) ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_macro_alert_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    fred = MagicMock()
    fred.get_economic_calendar = AsyncMock(
        return_value=[
            {
                "event": "Fed Interest Rate Decision",
                "impact": "low",
                "actual": "5.0",
                "estimate": "5.0",
                "previous": "5.25",
                "country": "US",
                "time": "2024-01-31 18:00",
            }
        ]
    )

    llm_client = MagicMock()
    llm_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="符合预期"))])
    )
    llm = MagicMock()
    llm.get_client = lambda: llm_client
    llm.get_model = lambda: "gpt"

    notify = MagicMock()
    notify.send_alert = AsyncMock()

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.zadd = AsyncMock()

    with (
        patch.object(md, "redis_client", redis),
        patch("backend.services.llm_service.llm_service", llm),
        patch("backend.services.notification_service.notification_service", notify),
        patch("backend.services.macro.fred_service.fred_service", fred),
    ):
        with pytest.raises(_BreakLoop):
            await md._macro_alert_daemon()


# ── _insider_transactions_marquee_daemon (505-555) ─────────────────────────────
@pytest.mark.asyncio
async def test_insider_marquee_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    finnhub = MagicMock()
    finnhub.get_insider_transactions = AsyncMock(
        return_value={
            "status": "success",
            "data": [
                {
                    "change": 20000,
                    "transaction_price": 100.0,
                    "date": "2024-01-01",
                    "name": "CEO Cook",
                }
            ],
        }
    )

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.zadd = AsyncMock()
    redis.zremrangebyrank = AsyncMock()

    with patch.object(md, "redis_client", redis):
        with pytest.raises(_BreakLoop):
            await md._insider_transactions_marquee_daemon(finnhub)


# ── _company_news_daemon (255-289) ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_company_news_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    finnhub = MagicMock()
    finnhub.subscribe_company_news = AsyncMock()
    finnhub.run_forever = AsyncMock()

    with pytest.raises(_BreakLoop):
        await md._company_news_daemon(finnhub)


# ── _news_stream_daemon (184-206) ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_news_stream_daemon(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    async def _empty():
        return
        yield

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = lambda: _empty()

    redis = MagicMock()
    redis.pubsub = AsyncMock(return_value=pubsub)

    finnhub = MagicMock()
    with patch.object(md, "redis_client", redis):
        with pytest.raises(_BreakLoop):
            await md._news_stream_daemon(finnhub)
