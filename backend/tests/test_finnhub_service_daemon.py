import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

DM = "backend.workers.market.daemon"


def _make_cancelling_sleep(after_n=0):
    """生成一个 sleep,在第 after_n 次调用后抛 CancelledError 中断 while True。"""
    counter = {"n": 0}

    async def _fake_sleep(_seconds):
        counter["n"] += 1
        if counter["n"] > after_n:
            raise asyncio.CancelledError()

    return _fake_sleep


def _flush_insider_redis():
    """清空持久化 redis 中 insider 跑马灯相关的残留键。

    CI 使用跨运行持久化的共享 redis, 历史 job 可能已写入当日
    `quant:insider_dedup:*` 去重键。一旦本测试的 redis mock 因并行时序
    偶发未生效而落到真实 redis, 已存在的去重键会让 `set nx` 返回 falsy,
    从而跳过 `zadd` 导致断言失败。运行前主动清空这些键以排除跨运行污染。
    """
    try:
        from backend.core.redis_client import redis_client as _rc

        for key in _rc.keys("quant:insider_dedup:*"):
            _rc.delete(key)
        _rc.delete("quant:insider_marquee")
    except Exception:
        # redis 不可用时跳过, 不影响 mock 路径
        pass


class TestMarketDaemon:
    """market_daemon 守护进程测试（已拆分至独立模块，仅 Master 运行）"""

    @pytest.fixture
    def service(self):
        from backend.services.finnhub.service import FinnhubService

        return FinnhubService()

    # ─── _get_proxy (仍在 finnhub_service) ──────────────────────
    def test_get_proxy_no_pool_returns_none(self, service):
        with patch.dict(os.environ, {"PROXY_POOL": ""}, clear=False):
            assert service._get_proxy() is None

    def test_get_proxy_with_pool_returns_one_of_them(self, service):
        pool = "http://1.1.1.1:8080, http://2.2.2.2:8080"
        with patch.dict(os.environ, {"PROXY_POOL": pool}, clear=False):
            proxy = service._get_proxy()
        assert proxy in ["http://1.1.1.1:8080", "http://2.2.2.2:8080"]

    # ─── _earnings_alert_daemon ─────────────────────────────────
    @pytest.mark.asyncio
    async def test_earnings_alert_daemon_error_status_continues_then_cancels(self, service):
        from backend.workers.market.daemon import _earnings_alert_daemon

        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(service, "get_earnings_calendar", new=AsyncMock(return_value={"status": "error"})),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _earnings_alert_daemon(service)

    @pytest.mark.asyncio
    async def test_earnings_alert_daemon_published_earnings_triggers_alert(self, service):
        from backend.workers.market.daemon import _earnings_alert_daemon

        row = {
            "symbol": "AAPL",
            "epsActual": 1.5,
            "epsEstimate": 1.2,
            "revenueActual": 1e9,
            "revenueEstimate": 9e8,
            "quarter": 3,
            "date": "2026-06-29",
        }
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_earnings_calendar", new=AsyncMock(return_value={"status": "success", "data": [row]})
            ),
            patch(f"{DM}.redis_client") as m_r,
            patch("backend.services.alert.notification.notification_service") as m_n,
            patch("backend.services.ai_narrator.llm_service.llm_service") as m_llm,
        ):
            m_r.set = AsyncMock(return_value=True)
            m_llm.get_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
            )
            with pytest.raises(asyncio.CancelledError):
                await _earnings_alert_daemon(service)
        m_n.send_alert.assert_called_once()

    # ─── _news_stream_daemon ────────────────────────────────────
    @pytest.mark.asyncio
    async def test_news_stream_daemon_no_api_key_returns_immediately(self, service):
        from backend.workers.market.daemon import _news_stream_daemon

        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            await _news_stream_daemon(service)

    @pytest.mark.asyncio
    async def test_news_stream_daemon_initial_snapshot_then_cancels(self, service):
        from backend.workers.market.daemon import _news_stream_daemon

        news = [{"headline": "fed cuts rates", "datetime": 1719500000, "summary": ""}]
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(service, "get_market_news", new=AsyncMock(return_value={"status": "success", "data": news})),
            patch(f"{DM}.redis_client") as m_r,
            patch("backend.services.macro.sentiment_service.sentiment_service") as m_s,
            patch(f"{DM}._get_news_tags_rules", new=AsyncMock(return_value={"FED": r"\bfed\b"})),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_s.batch_analyze_news = AsyncMock(return_value=news)
            with pytest.raises(asyncio.CancelledError):
                await _news_stream_daemon(service)
        m_r.zadd.assert_called()

    # ─── _company_news_daemon ───────────────────────────────────
    @pytest.mark.asyncio
    async def test_company_news_daemon_no_monitored_continues_then_cancels(self, service):
        from backend.workers.market.daemon import _company_news_daemon

        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch(f"{DM}.redis_client") as m_r,
        ):
            m_r.hkeys = AsyncMock(return_value=[])
            with pytest.raises(asyncio.CancelledError):
                await _company_news_daemon(service)

    @pytest.mark.asyncio
    async def test_company_news_daemon_with_ticker_publishes_new_news(self, service):
        from backend.workers.market.daemon import _company_news_daemon

        news = [{"headline": "AAPL launches new product", "datetime": 1719500000}]
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(2)),
            patch(f"{DM}.redis_client") as m_r,
            patch(f"{DM}.is_my_shard", return_value=True),
            patch.object(service, "get_company_news", new=AsyncMock(return_value={"status": "success", "data": news})),
        ):
            m_r.hkeys = AsyncMock(return_value=[b"US.AAPL"])
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await _company_news_daemon(service)
        m_r.publish.assert_called()

    # ─── _macro_alert_daemon ────────────────────────────────────
    @pytest.mark.asyncio
    async def test_macro_alert_daemon_no_data_continues_then_cancels(self, service):
        from backend.workers.market.daemon import _macro_alert_daemon

        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch("backend.services.akshare.akshare_service") as m_ak,
            patch("backend.services.macro.fred_service.fred_service") as m_fr,
        ):
            m_ak.get_economic_calendar_ak = AsyncMock(return_value={"status": "error"})
            m_fr.get_economic_calendar = AsyncMock(return_value={"status": "error"})
            with pytest.raises(asyncio.CancelledError):
                await _macro_alert_daemon()

    @pytest.mark.asyncio
    async def test_macro_alert_daemon_high_impact_published_triggers_alert(self, service):
        from backend.workers.market.daemon import _macro_alert_daemon

        event = {
            "event": "FOMC Rate Decision",
            "impact": "high",
            "actual": 5.25,
            "estimate": 5.0,
            "previous": 5.0,
            "country": "US",
            "time": "2026-06-29 14:00",
        }
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            # RL-11 修复：daemon 实际经由 data_source_router.fetch_akshare 取宏观日历，
            # 原 mock（akshare_service）从未被调用，导致永远走 fallback 且 alert 不触发
            patch(
                "backend.services.datasource.router.data_source_router.fetch_akshare",
                new=AsyncMock(return_value={"status": "success", "data": [event]}),
            ),
            patch(f"{DM}.redis_client") as m_r,
            patch("backend.services.alert.notification.notification_service") as m_n,
            patch("backend.services.ai_narrator.llm_service.llm_service") as m_llm,
        ):
            m_r.set = AsyncMock(return_value=True)
            m_llm.get_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="hawkish"))])
            )
            with pytest.raises(asyncio.CancelledError):
                await _macro_alert_daemon()
        m_n.send_alert.assert_called_once()

    # ─── _insider_transactions_marquee_daemon ───────────────────
    @pytest.mark.asyncio
    async def test_insider_marquee_daemon_significant_txn_added_to_zset(self, service):
        from datetime import datetime as _dt

        from backend.workers.market.daemon import _insider_transactions_marquee_daemon

        _flush_insider_redis()
        today_str = _dt.now().strftime("%Y-%m-%d")
        tx = {"change": 20000, "transaction_price": 100.0, "date": today_str, "name": "CEO Cook"}
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_insider_transactions", new=AsyncMock(return_value={"status": "success", "data": [tx]})
            ),
            patch(f"{DM}.redis_client") as m_r,
        ):
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await _insider_transactions_marquee_daemon(service)
        m_r.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_insider_marquee_daemon_old_txn_skipped(self, service):
        from backend.workers.market.daemon import _insider_transactions_marquee_daemon

        _flush_insider_redis()
        tx = {"change": 20000, "transaction_price": 100.0, "date": "2020-01-01", "name": "CEO Cook"}
        with (
            patch(f"{DM}.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_insider_transactions", new=AsyncMock(return_value={"status": "success", "data": [tx]})
            ),
            patch(f"{DM}.redis_client") as m_r,
        ):
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await _insider_transactions_marquee_daemon(service)
        m_r.zadd.assert_not_called()

    # ─── run_global_daemon ──────────────────────────────────────
    @pytest.mark.asyncio
    async def test_run_global_daemon_invokes_all_six_daemons(self, service):
        with (
            patch(f"{DM}._news_stream_daemon", new=AsyncMock()) as m1,
            patch(f"{DM}._company_news_daemon", new=AsyncMock()) as m2,
            patch(f"{DM}._trade_stream_daemon", new=AsyncMock()) as m3,
            patch(f"{DM}._macro_alert_daemon", new=AsyncMock()) as m4,
            patch(f"{DM}._insider_transactions_marquee_daemon", new=AsyncMock()) as m5,
            patch(f"{DM}._earnings_alert_daemon", new=AsyncMock()) as m6,
        ):
            from backend.workers.market.daemon import run_global_daemon

            await run_global_daemon()
        m1.assert_awaited_once()
        m2.assert_awaited_once()
        m3.assert_awaited_once()
        m4.assert_awaited_once()
        m5.assert_awaited_once()
        m6.assert_awaited_once()
