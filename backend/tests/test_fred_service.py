"""
FREDService 宏观经济数据服务单元测试
覆盖: get_series_observations, get_economic_calendar, close

BE-ARCH-07f: 主服务已卸载 FRED REST 直连，全部经 DataSourceRouter 远程代理，
因此本测试统一 mock `data_source_router.fetch_fred`。
"""

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

_ROUTER = "backend.services.macro.fred_service.data_source_router"


class TestFREDService:
    """FREDService 宏观经济数据服务测试"""

    @pytest.fixture
    def service(self):
        from backend.services.macro.fred_service import FREDService

        return FREDService()

    @pytest.mark.asyncio
    async def test_get_series_observations_cache_hit_returns_cached(self, service):
        """缓存命中应直接返回缓存数据，且不触发远程调用"""
        cached = {"status": "success", "series_id": "DGS10", "data": [{"date": "2026-01-01", "value": 4.5}]}
        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock()) as mock_fetch,
        ):
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            result = await service.get_series_observations("DGS10")
            assert result == cached
            mock_redis.get.assert_awaited()
            mock_fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_series_observations_success_returns_observations(self, service):
        """正常路径: 远程返回原始 observations 应归一化并写缓存"""
        remote = {
            "status": "success",
            "data": {
                "observations": [
                    {"date": "2026-06-01", "value": "4.5"},
                    {"date": "2026-06-02", "value": "."},  # 缺失值场景
                ]
            },
        }

        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value=remote)) as mock_fetch,
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            result = await service.get_series_observations("DGS10")
            assert result["status"] == "success"
            assert result["series_id"] == "DGS10"
            assert len(result["data"]) == 2
            assert result["data"][0]["value"] == 4.5
            assert result["data"][1]["value"] is None  # "." 应转为 None
            mock_redis.set.assert_awaited()
            mock_fetch.assert_awaited_once_with("macro_series", series_id="DGS10", limit=100)

    @pytest.mark.asyncio
    async def test_get_series_observations_accepts_normalized_list(self, service):
        """远程若已返回归一化列表，也应正确解析"""
        remote = {"status": "success", "data": [{"date": "2026-06-01", "value": "4.5"}]}

        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value=remote)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "success"
            assert result["data"] == [{"date": "2026-06-01", "value": 4.5}]

    @pytest.mark.asyncio
    async def test_get_series_observations_empty_observations_returns_warning(self, service):
        """空观测值列表应如实标记为 error（零幻觉红线），禁止伪装成 warning"""
        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value={"status": "success", "data": {"observations": []}})),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("UNKNOWN")
            assert result["status"] == "error"
            assert result["data"] == []
            assert "未返回有效观测数据" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_remote_error_returns_error(self, service):
        """远程子服务失败应返回 error 并透传原因"""
        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value={"status": "error", "message": "no healthy node"})),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "no healthy node" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_remote_none_returns_error(self, service):
        """远程返回非 dict（如 None）应安全降级为 error"""
        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value=None)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_get_economic_calendar_cache_hit_returns_cached(self, service):
        """缓存命中应直接返回"""
        cached = {"status": "success", "data": [{"event": "FOMC"}], "source": "fred"}
        with patch("backend.services.macro.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            result = await service.get_economic_calendar()
            assert result == cached

    @pytest.mark.asyncio
    async def test_get_economic_calendar_success_returns_events(self, service):
        """正常路径: 应返回过滤后的事件列表"""
        remote = {
            "status": "success",
            "data": {
                "release_dates": [
                    {"date": "2099-01-01", "release_name": "Employment Situation"},  # 远未来跳过
                    {"date": "2026-06-30", "release_name": "FOMC Meeting"},
                    {"date": "2026-06-30", "release_name": ""},  # 空 name 跳过
                ]
            },
        }

        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch("backend.services.macro.fred_service.datetime") as mock_dt,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value=remote)) as mock_fetch,
            patch.object(service, "backfill_actuals", AsyncMock(side_effect=lambda events: events)),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            from datetime import datetime, timezone

            fixed_now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
            mock_dt.now.return_value = fixed_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            result = await service.get_economic_calendar(days_ahead=7)
            assert result["status"] == "success"
            assert result["source"] == "fred"
            # 只保留 2026-06-30 的 FOMC Meeting 一条
            assert len(result["data"]) == 1
            assert result["data"][0]["event"] == "FOMC Meeting"
            mock_fetch.assert_awaited_once_with("releases_dates", limit=1000, sort_order="desc")

    @pytest.mark.asyncio
    async def test_get_economic_calendar_remote_error_returns_error(self, service):
        """远程失败应返回 error"""
        with (
            patch("backend.services.macro.fred_service.redis_client") as mock_redis,
            patch(f"{_ROUTER}.fetch_fred", AsyncMock(return_value={"status": "error", "message": "boom"})),
        ):
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_economic_calendar()
            assert result["status"] == "error"
            assert "宏观日历请求异常" in result["message"]

    @pytest.mark.asyncio
    async def test_close_is_noop(self, service):
        """远程化后 close 不再持有连接池，应安全空操作"""
        assert await service.close() is None
