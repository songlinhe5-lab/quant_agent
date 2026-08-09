"""
AKShareService A 股/港股通数据源单元测试（连接层已下沉 data_subservice）

覆盖: get_health_status, get_southbound_flow, get_northbound_flow,
      get_hsgt_top_holders, get_company_news, get_stock_quote,
      get_stock_history, get_economic_calendar

测试策略: 主服务不再持有 akshare 本地连接，所有数据经
data_source_router.fetch_akshare() 远程获取，故此处 mock 远程路由返回
子服务约定结构，断言主服务侧的缓存/熔断/降级/解析透传逻辑。
"""

import json
import os
import sys
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


@asynccontextmanager
async def _fake_lock_cm(*args, **kwargs):
    """模拟 _acquire_lock_with_timeout，立即返回上下文"""
    yield


class TestAKShareService:
    """AKShareService 数据源服务测试"""

    @pytest.fixture
    def service(self):
        from backend.services.akshare import AKShareService

        return AKShareService()

    @pytest.fixture(autouse=True)
    def _patch_lock(self):
        """自动 patch _acquire_lock_with_timeout 以避免真实 Redis 锁"""
        from backend.services.akshare import AKShareService

        with patch.object(AKShareService, "_acquire_lock_with_timeout", _fake_lock_cm):
            yield

    def test_get_health_status_states(self, service):
        """健康状态应反映 circuit_breaker 与 error_count"""
        service._circuit_breaker_until = 0.0
        service._error_count = 0
        assert service.get_health_status()["status"] == "healthy"
        service._error_count = 1
        assert service.get_health_status()["status"] == "warning"
        service._circuit_breaker_until = time.time() + 30.0
        assert service.get_health_status()["status"] == "circuit_open"

    @pytest.mark.asyncio
    async def test_get_southbound_flow_cache_hit(self, service):
        """南向资金缓存命中应直接返回"""
        cached = {"status": "success", "data": {"net_inflow": 12.8}}
        with patch("backend.services.akshare.flow.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            assert await service.get_southbound_flow() == cached

    @pytest.mark.asyncio
    async def test_get_southbound_flow_success(self, service):
        """南向资金正常路径（远程返回子服务结构）"""
        remote = {
            "status": "success",
            "data": {
                "net_inflow": 12.8,
                "weekly": 50.0,
                "monthly": 200.0,
                "unit": "亿人民币",
                "date": "2026-06-29",
                "sparkline": [1, 1, -1, 1],
                "history": [1, 1, -1, 1],
            },
            "is_closed": True,
            "source": "akshare_stock_hsgt_fund_flow_summary",
        }
        with (
            patch("backend.services.akshare.flow.redis_client") as mock_redis,
            patch("backend.services.akshare.flow.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_southbound_flow()
            assert result["status"] == "success"
            assert result["data"]["net_inflow"] == 12.8
            assert result["is_closed"] is True
            mock_router.fetch_akshare.assert_awaited_once_with("SOUTHBOUND")

    @pytest.mark.asyncio
    async def test_get_southbound_flow_failure_returns_mock(self, service):
        """南向资金获取异常应返回降级 warning，禁止注入 mock 假数字"""
        with (
            patch("backend.services.akshare.flow.redis_client") as mock_redis,
            patch("backend.services.akshare.flow.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(side_effect=RuntimeError("boom"))
            result = await service.get_southbound_flow()
            assert result["status"] == "warning"
            assert result["data"] is None
            assert result["source"] == "akshare-unavailable"

    @pytest.mark.asyncio
    async def test_get_northbound_flow_success(self, service):
        """北向资金正常路径（远程返回子服务结构）"""
        remote = {
            "status": "success",
            "data": {
                "net_inflow": -5.3,
                "weekly": -10.0,
                "monthly": -30.0,
                "unit": "亿人民币",
                "date": "2026-06-29",
                "sparkline": [-1, -1, 1, -1],
                "history": [-1, -1, 1, -1],
            },
            "is_closed": True,
            "source": "akshare_stock_hsgt_fund_flow_summary",
        }
        with (
            patch("backend.services.akshare.flow.redis_client") as mock_redis,
            patch("backend.services.akshare.flow.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_northbound_flow()
            assert result["status"] == "success"
            assert result["data"]["net_inflow"] == -5.3
            mock_router.fetch_akshare.assert_awaited_once_with("FUND_FLOW")

    @pytest.mark.asyncio
    async def test_get_company_news_circuit_open_returns_error(self, service):
        """熔断开启时应直接返回 error"""
        service._circuit_breaker_until = time.time() + 30
        result = await service.get_company_news("SH.600519")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_company_news_block_index_returns_warning(self, service):
        """板块指数代码应返回 warning（不触网）"""
        with patch("backend.services.akshare.quote.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_company_news("HK.BK1118")
            assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_get_company_news_hk_fallback_yahoo(self, service):
        """港股代码应通过 Yahoo 兜底获取新闻"""
        yahoo_news = [{"headline": "h1"}, {"headline": "h2"}]
        with (
            patch("backend.services.akshare.quote.redis_client") as mock_redis,
            patch(
                "backend.core.yahoo_news.fetch_yahoo_news",
                new=AsyncMock(return_value=yahoo_news),
            ),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_company_news("HK.00700")
            assert result["status"] == "success"
            assert result["source"] == "yahoo_fallback"
            assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_company_news_invalid_code_returns_error(self, service):
        """无法提取数字代码时应返回 error"""
        with patch("backend.services.akshare.quote.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            assert (await service.get_company_news("INVALID"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_company_news_akshare_success(self, service):
        """A股新闻应远程调 STOCK_NEWS 并透传"""
        news = [{"headline": "a", "date": "2026-06-29 10:00:00"}]
        remote = {"status": "success", "data": news, "source": "akshare"}
        with (
            patch("backend.services.akshare.quote.redis_client") as mock_redis,
            patch("backend.services.akshare.quote.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_company_news("SH.600519")
            assert result["status"] == "success"
            assert result["data"] == news
            mock_router.fetch_akshare.assert_awaited_once_with("STOCK_NEWS", ticker="SH.600519")

    @pytest.mark.asyncio
    async def test_get_stock_quote_circuit_open_returns_error(self, service):
        """熔断开启时应直接返回 error"""
        service._circuit_breaker_until = time.time() + 30
        assert (await service.get_stock_quote("SH.600519"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_stock_quote_invalid_code(self, service):
        """无效代码应返回 error"""
        with patch("backend.services.akshare.quote.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            assert (await service.get_stock_quote("INVALID"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_stock_quote_success(self, service):
        """A股行情正常路径（远程返回子服务结构）"""
        remote = {
            "status": "success",
            "data": {
                "ticker": "SH.600519",
                "last_price": 102.0,
                "open": 101.0,
                "high": 103.0,
                "low": 100.0,
                "prev_close": 101.0,
                "volume": 11000,
                "turnover": 1100000,
                "change_val": 1.0,
                "change_pct": 0.99,
                "amplitude": 2.97,
                "volume_str": "11.00K",
            },
            "source": "akshare_sina",
        }
        with (
            patch("backend.services.akshare.quote.redis_client") as mock_redis,
            patch("backend.services.akshare.quote.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_stock_quote("SH.600519")
            assert result["status"] == "success"
            assert result["data"]["last_price"] == 102.0
            mock_router.fetch_akshare.assert_awaited_once_with("QUOTE_A", ticker="SH.600519")

    @pytest.mark.asyncio
    async def test_get_stock_history_success(self, service):
        """A股历史 K 线正常路径（远程返回子服务结构）"""
        remote = {
            "status": "success",
            "data": [
                {
                    "time": "2026-06-28 00:00:00",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 10000,
                },
                {
                    "time": "2026-06-29 00:00:00",
                    "open": 101.0,
                    "high": 103.0,
                    "low": 100.0,
                    "close": 102.0,
                    "volume": 11000,
                },
            ],
            "source": "akshare_fallback",
        }
        with (
            patch("backend.services.akshare.quote.redis_client") as mock_redis,
            patch("backend.services.akshare.quote.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_stock_history("SH.600519", num=2)
            assert result["status"] == "success"
            assert len(result["data"]) == 2
            mock_router.fetch_akshare.assert_awaited_once_with("HISTORY_A", ticker="SH.600519", num=2)

    @pytest.mark.asyncio
    async def test_get_hsgt_top_holders_success(self, service):
        """沪深港通持仓明细正常路径（远程返回子服务结构）"""
        remote = {
            "status": "success",
            "data": {
                "symbol": "00700",
                "date": "2026-06-29",
                "southbound_total_shares": 1500.0,
                "southbound_net_change": 500.0,
                "participants": [
                    {"holder": "A", "shares": 1500.0, "net_change": 500.0, "pct": 1.5, "is_southbound": True}
                ],
                "total_shares_sampled": 1500.0,
            },
            "source": "akshare_stock_hsgt_individual_detail",
        }
        with (
            patch("backend.services.akshare.flow.redis_client") as mock_redis,
            patch("backend.services.akshare.flow.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_hsgt_top_holders("00700")
            assert result["status"] == "success"
            assert result["data"]["southbound_total_shares"] == 1500.0
            assert len(result["data"]["participants"]) == 1
            mock_router.fetch_akshare.assert_awaited_once_with("HSGT_HOLDERS", symbol="00700")

    @pytest.mark.asyncio
    async def test_get_hsgt_top_holders_empty_returns_warning(self, service):
        """空数据应返回 warning"""
        remote = {"status": "warning", "message": "空", "data": None}
        with (
            patch("backend.services.akshare.flow.redis_client") as mock_redis,
            patch("backend.services.akshare.flow.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            assert (await service.get_hsgt_top_holders("00700"))["status"] == "warning"

    @pytest.mark.asyncio
    async def test_get_economic_calendar_cache_hit(self, service):
        """宏观日历缓存命中"""
        cached = {"status": "success", "data": [{"event": "FOMC"}]}
        with patch("backend.services.akshare.calendar.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            assert await service.get_economic_calendar() == cached

    @pytest.mark.asyncio
    async def test_get_economic_calendar_success(self, service):
        """远程经济日历成功路径"""
        remote = {"status": "success", "data": [{"event": "FOMC", "country": "美国"}], "source": "akshare_universal"}
        with (
            patch("backend.services.akshare.calendar.redis_client") as mock_redis,
            patch("backend.services.akshare.calendar.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            mock_router.fetch_akshare = AsyncMock(return_value=remote)
            result = await service.get_economic_calendar(days_ahead=0)
            assert result["status"] == "success"
            assert result["source"] == "akshare_universal"
            mock_router.fetch_akshare.assert_awaited_once_with("ECONOMIC_CALENDAR", days_ahead=0, days_back=0)

    @pytest.mark.asyncio
    async def test_get_economic_calendar_exception_returns_error(self, service):
        """远程异常应返回 error"""
        with (
            patch("backend.services.akshare.calendar.redis_client") as mock_redis,
            patch("backend.services.akshare.calendar.data_source_router") as mock_router,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_router.fetch_akshare = AsyncMock(side_effect=RuntimeError("boom"))
            assert (await service.get_economic_calendar())["status"] == "error"

    def test_mock_helpers_return_warning(self, service):
        """_mock_southbound / _mock_northbound 应返回 warning 状态"""
        assert service._mock_southbound()["status"] == "warning"
        assert service._mock_northbound()["status"] == "warning"
