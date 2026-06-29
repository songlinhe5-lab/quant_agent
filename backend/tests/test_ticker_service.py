"""
TickerService 标的代码解析/映射服务单元测试
覆盖: search_tickers, sync_tickers_daemon, _write_base_tickers, _fetch_and_save_from_futu
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


class TestTickerService:
    """TickerService 标的词库与搜索服务测试"""

    @pytest.fixture
    def service(self):
        from backend.services.ticker_service import TickerService

        return TickerService()

    @pytest.mark.asyncio
    async def test_search_tickers_empty_query_returns_empty(self, service):
        """空 query 应直接返回空列表"""
        result = await service.search_tickers("")
        assert result["status"] == "success"
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_search_tickers_too_long_query_returns_empty(self, service):
        """超长 query 应被防御性拦截"""
        result = await service.search_tickers("A" * 51)
        assert result["status"] == "success"
        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_search_tickers_cache_hit_returns_cached(self, service):
        """Redis 缓存命中应直接返回缓存数据"""
        cached_data = [{"symbol": "US.AAPL", "name": "Apple", "type": "EQUITY"}]
        with patch("backend.services.ticker_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value='[{"symbol": "US.AAPL", "name": "Apple", "type": "EQUITY"}]')
            result = await service.search_tickers("AAPL")
            assert result["status"] == "success"
            assert result["data"] == cached_data
            mock_redis.get.assert_awaited()

    @pytest.mark.asyncio
    async def test_search_tickers_db_query_returns_results(self, service):
        """缓存未命中时应触发数据库查询并写回缓存"""
        cached_data = [{"symbol": "US.AAPL", "name": "Apple Inc.", "type": "EQUITY"}]

        async def fake_to_thread(func, *args, **kwargs):
            return cached_data

        with (
            patch("backend.services.ticker_service.redis_client") as mock_redis,
            patch("backend.services.ticker_service.asyncio.to_thread", new=fake_to_thread),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            result = await service.search_tickers("AAPL")
            assert result["status"] == "success"
            assert result["data"] == cached_data
            mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_search_tickers_db_exception_returns_error(self, service):
        """数据库异常应返回 error 状态"""
        with (
            patch("backend.services.ticker_service.redis_client") as mock_redis,
            patch("backend.services.ticker_service.asyncio.to_thread", side_effect=RuntimeError("db fail")),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.search_tickers("AAPL")
            assert result["status"] == "error"
            assert "SQL 搜索异常" in result["message"]

    @pytest.mark.asyncio
    async def test_sync_tickers_daemon_already_running_returns(self, service):
        """守护进程已在运行时应直接返回"""
        service.sync_running = True
        await service.sync_tickers_daemon()
        # 无异常即通过

    @pytest.mark.asyncio
    async def test_sync_tickers_daemon_runs_one_cycle(self, service):
        """守护进程应执行一轮同步后进入休眠"""
        service.sync_running = False

        async def fake_sleep(seconds):
            service.sync_running = False  # 退出循环
            raise asyncio.CancelledError

        with (
            patch("backend.services.ticker_service.asyncio.to_thread", new=AsyncMock()) as mock_thread,
            patch("backend.services.ticker_service.asyncio.sleep", new=fake_sleep),
            patch("backend.services.futu.futu_service.status", "DISCONNECTED"),
        ):
            mock_thread.return_value = []
            try:
                await service.sync_tickers_daemon()
            except asyncio.CancelledError:
                pass
            assert mock_thread.await_count >= 1

    def test_write_base_tickers_writes_to_db(self, service):
        """_write_base_tickers 应向数据库 merge 基础标的并 commit"""
        with patch("backend.services.ticker_service.SessionLocal") as mock_session_cls:
            mock_db = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)
            result = service._write_base_tickers()
            assert len(result) > 0
            assert mock_db.merge.call_count == len(result)
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_and_save_from_futu_success(self, service):
        """Futu 已连接时应批量拉取并入库"""
        fake_res = {
            "status": "success",
            "data": [
                {"code": "HK.00700", "name": "腾讯"},
                {"code": "", "name": "应跳过空代码"},
            ],
        }

        async def fake_get(market, sec_type):
            return fake_res

        async def fake_to_thread(func, *args, **kwargs):
            # 真实执行 _bulk_upsert 以验证 commit 行为
            return func()

        with (
            patch("backend.services.ticker_service.futu_service") as mock_futu,
            patch("backend.services.ticker_service.SessionLocal") as mock_session_cls,
            patch("backend.services.ticker_service.asyncio.to_thread", new=fake_to_thread),
        ):
            mock_futu.get_stock_basicinfo = fake_get
            mock_db = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = await service._fetch_and_save_from_futu()
            # 4 个组合 (HK/US x STOCK/ETF) * 1 个有效 code = 4
            assert len(result) == 4
            assert all(r["symbol"] == "HK.00700" for r in result)
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_and_save_from_futu_skips_when_no_data(self, service):
        """Futu 返回非 success 时不应写入任何数据"""

        async def fake_get(market, sec_type):
            return {"status": "error", "data": []}

        with patch("backend.services.ticker_service.futu_service") as mock_futu:
            mock_futu.get_stock_basicinfo = fake_get
            result = await service._fetch_and_save_from_futu()
            assert result == []
