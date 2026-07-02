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


def _make_cancelling_sleep(after_n=0):
    """生成一个 sleep,在第 after_n 次调用后抛 CancelledError 中断 while True。"""
    counter = {"n": 0}

    async def _fake_sleep(_seconds):
        counter["n"] += 1
        if counter["n"] > after_n:
            raise asyncio.CancelledError()

    return _fake_sleep


class TestFinnhubServiceDaemon:
    """finnhub_service 守护进程与代理池等未测方法补强测试"""

    @pytest.fixture
    def service(self):
        from backend.services.finnhub_service import FinnhubService

        return FinnhubService()

    # ─── _get_proxy ──────────────────────────────────────────────
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
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(service, "get_earnings_calendar", new=AsyncMock(return_value={"status": "error"})),
        ):
            with pytest.raises(asyncio.CancelledError):
                await service._earnings_alert_daemon()

    @pytest.mark.asyncio
    async def test_earnings_alert_daemon_published_earnings_triggers_alert(self, service):
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
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_earnings_calendar", new=AsyncMock(return_value={"status": "success", "data": [row]})
            ),
            patch("backend.services.finnhub_service.redis_client") as m_r,
            patch("backend.services.notification_service.notification_service") as m_n,
            patch("backend.services.finnhub_service.llm_service") as m_llm,
        ):
            m_r.set = AsyncMock(return_value=True)
            m_llm.get_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="ok"))])
            )
            with pytest.raises(asyncio.CancelledError):
                await service._earnings_alert_daemon()
        m_n.send_alert.assert_called_once()

    # ─── _news_stream_daemon ────────────────────────────────────
    @pytest.mark.asyncio
    async def test_news_stream_daemon_no_api_key_returns_immediately(self, service):
        with patch.dict(os.environ, {"FINNHUB_API_KEY": ""}, clear=False):
            await service._news_stream_daemon()

    @pytest.mark.asyncio
    async def test_news_stream_daemon_initial_snapshot_then_cancels(self, service):
        news = [{"headline": "fed cuts rates", "datetime": 1719500000, "summary": ""}]
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(service, "get_market_news", new=AsyncMock(return_value={"status": "success", "data": news})),
            patch("backend.services.finnhub_service.redis_client") as m_r,
            patch("backend.services.finnhub_service.sentiment_service") as m_s,
            patch.object(service, "_get_news_tags_rules", new=AsyncMock(return_value={"FED": r"\bfed\b"})),
        ):
            m_r.set = AsyncMock(return_value=True)
            m_s.batch_analyze_news = AsyncMock(return_value=news)
            with pytest.raises(asyncio.CancelledError):
                await service._news_stream_daemon()
        m_r.zadd.assert_called()

    # ─── _company_news_daemon ───────────────────────────────────
    @pytest.mark.asyncio
    async def test_company_news_daemon_no_monitored_continues_then_cancels(self, service):
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch("backend.services.finnhub_service.redis_client") as m_r,
        ):
            m_r.hkeys = AsyncMock(return_value=[])
            with pytest.raises(asyncio.CancelledError):
                await service._company_news_daemon()

    @pytest.mark.asyncio
    async def test_company_news_daemon_with_ticker_publishes_new_news(self, service):
        news = [{"headline": "AAPL launches new product", "datetime": 1719500000}]
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(2)),
            patch("backend.services.finnhub_service.redis_client") as m_r,
            patch("backend.services.finnhub_service.is_my_shard", return_value=True),
            patch.object(service, "get_company_news", new=AsyncMock(return_value={"status": "success", "data": news})),
        ):
            m_r.hkeys = AsyncMock(return_value=[b"US.AAPL"])
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await service._company_news_daemon()
        m_r.publish.assert_called()

    # ─── _macro_alert_daemon ────────────────────────────────────
    @pytest.mark.asyncio
    async def test_macro_alert_daemon_no_data_continues_then_cancels(self, service):
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch("backend.services.akshare_service.akshare_service") as m_ak,
            patch("backend.services.fred_service.fred_service") as m_fr,
        ):
            m_ak.get_economic_calendar = AsyncMock(return_value={"status": "error"})
            m_fr.get_economic_calendar = AsyncMock(return_value={"status": "error"})
            with pytest.raises(asyncio.CancelledError):
                await service._macro_alert_daemon()

    @pytest.mark.asyncio
    async def test_macro_alert_daemon_high_impact_published_triggers_alert(self, service):
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
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch("backend.services.akshare_service.akshare_service") as m_ak,
            patch("backend.services.finnhub_service.redis_client") as m_r,
            patch("backend.services.notification_service.notification_service") as m_n,
            patch("backend.services.finnhub_service.llm_service") as m_llm,
        ):
            m_ak.get_economic_calendar = AsyncMock(return_value={"status": "success", "data": [event]})
            m_r.set = AsyncMock(return_value=True)
            m_llm.get_client.return_value.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="hawkish"))])
            )
            with pytest.raises(asyncio.CancelledError):
                await service._macro_alert_daemon()
        m_n.send_alert.assert_called_once()

    # ─── _insider_transactions_marquee_daemon ───────────────────
    @pytest.mark.asyncio
    async def test_insider_marquee_daemon_significant_txn_added_to_zset(self, service):
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")
        tx = {"change": 20000, "transaction_price": 100.0, "date": today_str, "name": "CEO Cook"}
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_insider_transactions", new=AsyncMock(return_value={"status": "success", "data": [tx]})
            ),
            patch("backend.services.finnhub_service.redis_client") as m_r,
        ):
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await service._insider_transactions_marquee_daemon()
        m_r.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_insider_marquee_daemon_old_txn_skipped(self, service):
        tx = {"change": 20000, "transaction_price": 100.0, "date": "2020-01-01", "name": "CEO Cook"}
        with (
            patch("backend.services.finnhub_service.asyncio.sleep", new=_make_cancelling_sleep(1)),
            patch.object(
                service, "get_insider_transactions", new=AsyncMock(return_value={"status": "success", "data": [tx]})
            ),
            patch("backend.services.finnhub_service.redis_client") as m_r,
        ):
            m_r.set = AsyncMock(return_value=True)
            with pytest.raises(asyncio.CancelledError):
                await service._insider_transactions_marquee_daemon()
        m_r.zadd.assert_not_called()

    # ─── run_global_daemon ──────────────────────────────────────
    @pytest.mark.asyncio
    async def test_run_global_daemon_invokes_all_six_daemons(self, service):
        with (
            patch.object(service, "_news_stream_daemon", new=AsyncMock()) as m1,
            patch.object(service, "_company_news_daemon", new=AsyncMock()) as m2,
            patch.object(service, "_trade_stream_daemon", new=AsyncMock()) as m3,
            patch.object(service, "_macro_alert_daemon", new=AsyncMock()) as m4,
            patch.object(service, "_insider_transactions_marquee_daemon", new=AsyncMock()) as m5,
            patch.object(service, "_earnings_alert_daemon", new=AsyncMock()) as m6,
        ):
            await service.run_global_daemon()
        m1.assert_awaited_once()
        m2.assert_awaited_once()
        m3.assert_awaited_once()
        m4.assert_awaited_once()
        m5.assert_awaited_once()
        m6.assert_awaited_once()
