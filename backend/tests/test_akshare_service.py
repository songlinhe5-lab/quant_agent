"""
AKShareService A 股/港股通数据源单元测试
覆盖: get_health_status, get_southbound_flow, get_northbound_flow,
      get_hsgt_top_holders, get_company_news, get_stock_quote,
      get_stock_history, get_economic_calendar
"""

import json
import os
import sys
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
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
        from backend.services.akshare_service import AKShareService

        return AKShareService()

    @pytest.fixture(autouse=True)
    def _patch_lock(self):
        """自动 patch _acquire_lock_with_timeout 以避免真实 Redis 锁"""
        from backend.services.akshare_service import AKShareService

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
        with patch("backend.services.akshare_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            assert await service.get_southbound_flow() == cached

    @pytest.mark.asyncio
    async def test_get_southbound_flow_success(self, service):
        """南向资金正常路径"""
        df = pd.DataFrame(
            {
                "资金方向": ["南向", "北向"],
                "资金净流入": [12.8, -5.3],
                "交易日": ["2026-06-29", "2026-06-29"],
                "交易状态": [3, 3],
            }
        )
        hist_df = pd.DataFrame({"当日成交净买额": [10, 12, 8]})
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.gather", new=AsyncMock(return_value=(df, hist_df))),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_southbound_flow()
            assert result["status"] == "success"
            assert result["data"]["net_inflow"] == 12.8
            assert result["is_closed"] is True

    @pytest.mark.asyncio
    async def test_get_southbound_flow_failure_returns_mock(self, service):
        """南向资金获取异常应返回 mock 数据"""
        with (
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.gather", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_southbound_flow()
            assert result["status"] == "warning"
            assert result["source"] == "mock"

    @pytest.mark.asyncio
    async def test_get_northbound_flow_success(self, service):
        """北向资金正常路径"""
        df = pd.DataFrame(
            {
                "资金方向": ["北向", "南向"],
                "资金净流入": [-5.3, 12.8],
                "交易日": ["2026-06-29", "2026-06-29"],
                "交易状态": [3, 3],
            }
        )
        hist_df = pd.DataFrame({"当日成交净买额": [-1, -2, -3]})
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.gather", new=AsyncMock(return_value=(df, hist_df))),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_northbound_flow()
            assert result["status"] == "success"
            assert result["data"]["net_inflow"] == -5.3

    @pytest.mark.asyncio
    async def test_get_company_news_circuit_open_returns_error(self, service):
        """熔断开启时应直接返回 error"""
        service._circuit_breaker_until = time.time() + 30
        result = await service.get_company_news("SH.600519")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_company_news_block_index_returns_warning(self, service):
        """板块指数代码应返回 warning"""
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_company_news("HK.BK1118")
            assert result["status"] == "warning"

    @pytest.mark.asyncio
    async def test_get_company_news_hk_fallback_yahoo(self, service):
        """港股代码应通过 Yahoo 兜底获取新闻"""
        yahoo_news = [{"headline": "h1"}, {"headline": "h2"}]
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch(
                "backend.services.finnhub_service.finnhub_service._fallback_yahoo_news",
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
        with patch("backend.services.akshare_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            assert (await service.get_company_news("INVALID"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_stock_quote_circuit_open_returns_error(self, service):
        """熔断开启时应直接返回 error"""
        service._circuit_breaker_until = time.time() + 30
        assert (await service.get_stock_quote("SH.600519"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_stock_quote_invalid_code(self, service):
        """无效代码应返回 error"""
        with patch("backend.services.akshare_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            assert (await service.get_stock_quote("INVALID"))["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_stock_quote_success(self, service):
        """A股行情正常路径"""
        df = pd.DataFrame(
            {
                "开盘": [100.0, 101.0],
                "最高": [102.0, 103.0],
                "最低": [99.0, 100.0],
                "收盘": [101.0, 102.0],
                "成交量": [10000, 11000],
                "成交额": [1000000, 1100000],
                "振幅": [3.0, 3.0],
            }
        )
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.to_thread", new=AsyncMock(return_value=df)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_stock_quote("SH.600519")
            assert result["status"] == "success"
            assert result["data"]["last_price"] == 102.0

    @pytest.mark.asyncio
    async def test_get_stock_history_success(self, service):
        """A股历史 K 线正常路径"""
        df = pd.DataFrame(
            {
                "日期": ["2026-06-28", "2026-06-29"],
                "开盘": [100.0, 101.0],
                "最高": [102.0, 103.0],
                "最低": [99.0, 100.0],
                "收盘": [101.0, 102.0],
                "成交量": [10000, 11000],
            }
        )
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.to_thread", new=AsyncMock(return_value=df)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_stock_history("SH.600519", num=2)
            assert result["status"] == "success"
            assert len(result["data"]) == 2

    @pytest.mark.asyncio
    async def test_get_hsgt_top_holders_success(self, service):
        """沪深港通持仓明细正常路径"""
        df = pd.DataFrame(
            {
                "持股日期": ["2026-06-28", "2026-06-28", "2026-06-29"],
                "机构名称": ["A 机构", "B 机构", "A 机构"],
                "持股数量": [1000.0, 2000.0, 1500.0],
                "持股数量占A股百分比": [1.0, 2.0, 1.5],
            }
        )
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.to_thread", new=AsyncMock(return_value=df)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_hsgt_top_holders("00700")
            assert result["status"] == "success"
            assert result["data"]["southbound_total_shares"] == 1500.0
            assert len(result["data"]["participants"]) == 1

    @pytest.mark.asyncio
    async def test_get_hsgt_top_holders_empty_returns_warning(self, service):
        """空 DataFrame 应返回 warning"""
        fake_ak = MagicMock()
        with (
            patch.dict(sys.modules, {"akshare": fake_ak}),
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.to_thread", new=AsyncMock(return_value=pd.DataFrame())),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            assert (await service.get_hsgt_top_holders("00700"))["status"] == "warning"

    @pytest.mark.asyncio
    async def test_get_economic_calendar_cache_hit(self, service):
        """宏观日历缓存命中"""
        cached = {"status": "success", "data": [{"event": "FOMC"}]}
        with patch("backend.services.akshare_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            assert await service.get_economic_calendar() == cached

    @pytest.mark.asyncio
    async def test_get_economic_calendar_success(self, service):
        """百度股市通接口应被优先调用"""
        df = pd.DataFrame({"地区": ["US"], "事件": ["FOMC"], "重要性": ["高"], "公布时间": ["08:30"]})
        with (
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch(
                "backend.services.akshare_service.asyncio.gather", new=AsyncMock(return_value=[df.to_dict("records")])
            ),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_economic_calendar(days_ahead=0)
            assert result["status"] == "success"
            assert result["source"] == "akshare_universal"

    @pytest.mark.asyncio
    async def test_get_economic_calendar_exception_returns_error(self, service):
        """gather 异常应返回 error"""
        with (
            patch("backend.services.akshare_service.redis_client") as mock_redis,
            patch("backend.services.akshare_service.asyncio.gather", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            assert (await service.get_economic_calendar())["status"] == "error"

    def test_mock_helpers_return_warning(self, service):
        """_mock_southbound / _mock_northbound 应返回 warning 状态"""
        assert service._mock_southbound()["status"] == "warning"
        assert service._mock_northbound()["status"] == "warning"
