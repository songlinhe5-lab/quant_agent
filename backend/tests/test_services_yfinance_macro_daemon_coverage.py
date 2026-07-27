"""补充 services/yfinance/macro_daemon.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行 (18-344):
- _router_enabled=True 早返回 (18-26)
- 主拉取路径: 分布式锁 -> yf.download -> 多线程处理 -> 缓存写入 -> 收盘总结推送 (27-219, 226-344)
- 空数据降级 (332-335)
- YFRateLimitError 重试 + 熔断器 record_failure (112-124)

依赖 yfinance 已装; 用 patch 替换 yfinance.download 返回构造 DataFrame, 不触网。
"""

import asyncio
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as _dt
from datetime import timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from backend.services.yfinance import macro_daemon as ymd
from backend.services.yfinance.macro_daemon import MacroDaemonMixin


class _BreakLoop(Exception):
    pass


def _make_sleep_breaker(monkeypatch):
    state = {"n": 0}

    async def _break(*a, **k):
        state["n"] += 1
        if state["n"] >= 2:
            raise _BreakLoop()

    monkeypatch.setattr(asyncio, "sleep", _break)


TICKERS = ["^GSPC", "^IXIC", "^HSI", "GC=F", "CL=F", "^VIX"]


def _make_df():
    dates = pd.to_datetime(["2024-01-01"])
    cols = pd.MultiIndex.from_product([TICKERS, ["Close", "Open"]], names=["ticker", "field"])
    return pd.DataFrame(1.0, index=dates, columns=cols)


class DummyMacroDaemon(MacroDaemonMixin):
    def __init__(self, router_enabled=False):
        self._router_enabled = router_enabled
        self._executor = ThreadPoolExecutor(max_workers=1)
        self.cb = MagicMock()
        self.llm_service = MagicMock()
        self.llm_service.get_client = lambda: MagicMock(
            chat=MagicMock(
                completions=MagicMock(
                    create=AsyncMock(return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="风险可控"))]))
                )
            )
        )
        self.llm_service.get_model = lambda: "gpt"
        self.session = MagicMock()


# ── router 模式早返回 (18-26) ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_router_mode_early_return(monkeypatch):
    async def _break_immediate(*a, **k):
        raise _BreakLoop()

    monkeypatch.setattr(asyncio, "sleep", _break_immediate)
    daemon = DummyMacroDaemon(router_enabled=True)
    with pytest.raises(_BreakLoop):
        await daemon.macro_data_daemon()


# ── 主拉取 + 处理 + 缓存 + 收盘总结 (27-219, 226-344) ─────────────────────────
def _fix_et_clock(monkeypatch):
    # 固定为 2024-01-01 21:00 UTC = 美东 16:00 (周一, 交易日)
    epoch = _dt(2024, 1, 1, 21, 0, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(_time, "time", lambda: epoch)
    monkeypatch.setattr(
        __import__("zoneinfo", fromlist=["ZoneInfo"]),
        "ZoneInfo",
        lambda *a, **k: timezone(timedelta(hours=-5)),
    )


@pytest.mark.asyncio
async def test_macro_daemon_success(monkeypatch):
    _make_sleep_breaker(monkeypatch)
    _fix_et_clock(monkeypatch)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.zrevrange = AsyncMock(return_value=[])
    batch_writer = MagicMock()
    batch_writer.put_set_nowait = MagicMock()

    notify = MagicMock()
    notify.send_alert = AsyncMock()

    daemon = DummyMacroDaemon()
    with (
        patch("yfinance.download", return_value=_make_df()),
        patch.object(ymd, "notification_service", notify),
        patch("backend.core.redis_client.redis_client", redis),
        patch("backend.core.redis_client.redis_batch_writer", batch_writer),
    ):
        with pytest.raises(_BreakLoop):
            await daemon.macro_data_daemon()


# ── 空数据降级 (332-335) ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_macro_daemon_empty_data(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.zrevrange = AsyncMock(return_value=[])
    batch_writer = MagicMock()
    batch_writer.put_set_nowait = MagicMock()
    notify = MagicMock()
    notify.send_alert = AsyncMock()

    daemon = DummyMacroDaemon()
    with (
        patch("yfinance.download", return_value=pd.DataFrame()),
        patch.object(ymd, "notification_service", notify),
        patch("backend.core.redis_client.redis_client", redis),
        patch("backend.core.redis_client.redis_batch_writer", batch_writer),
    ):
        with pytest.raises(_BreakLoop):
            await daemon.macro_data_daemon()


# ── YFRateLimitError 重试 + 熔断 (112-124) ───────────────────────────────────
@pytest.mark.asyncio
async def test_macro_daemon_rate_limit(monkeypatch):
    _make_sleep_breaker(monkeypatch)

    redis = MagicMock()
    redis.set = AsyncMock(return_value=True)
    redis.zrevrange = AsyncMock(return_value=[])
    batch_writer = MagicMock()
    batch_writer.put_set_nowait = MagicMock()
    notify = MagicMock()
    notify.send_alert = AsyncMock()

    daemon = DummyMacroDaemon()
    with (
        patch("yfinance.download", side_effect=Exception("YFRateLimitError: Too Many Requests")),
        patch.object(ymd, "notification_service", notify),
        patch("backend.core.redis_client.redis_client", redis),
        patch("backend.core.redis_client.redis_batch_writer", batch_writer),
    ):
        with pytest.raises(_BreakLoop):
            await daemon.macro_data_daemon()
    assert daemon.cb.record_failure.called
