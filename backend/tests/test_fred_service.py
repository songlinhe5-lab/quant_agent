"""
FREDService 宏观经济数据服务单元测试
覆盖: get_series_observations, get_economic_calendar, close
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestFREDService:
    """FREDService 宏观经济数据服务测试"""

    @pytest.fixture
    def service(self):
        from backend.services.fred_service import FREDService

        svc = FREDService()
        svc.api_key = "test-fred-key"
        svc.session = AsyncMock(spec=httpx.AsyncClient)
        return svc

    @pytest.mark.asyncio
    async def test_get_series_observations_no_api_key_returns_error(self):
        """未配置 API Key 应返回 error"""
        from backend.services.fred_service import FREDService

        svc = FREDService()
        svc.api_key = None
        result = await svc.get_series_observations("DGS10")
        assert result["status"] == "error"
        assert "API Key" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_cache_hit_returns_cached(self, service):
        """缓存命中应直接返回缓存数据"""
        cached = {"status": "success", "series_id": "DGS10", "data": [{"date": "2026-01-01", "value": 4.5}]}
        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            result = await service.get_series_observations("DGS10")
            assert result == cached
            mock_redis.get.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_series_observations_success_returns_observations(self, service):
        """正常路径: HTTP 200 应返回观测值并写缓存"""
        api_data = {
            "observations": [
                {"date": "2026-06-01", "value": "4.5"},
                {"date": "2026-06-02", "value": "."},  # 缺失值场景
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_data
        mock_resp.raise_for_status = MagicMock()
        service.session.get = AsyncMock(return_value=mock_resp)

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.set = AsyncMock()

            result = await service.get_series_observations("DGS10")
            assert result["status"] == "success"
            assert result["series_id"] == "DGS10"
            assert len(result["data"]) == 2
            assert result["data"][0]["value"] == 4.5
            assert result["data"][1]["value"] is None  # "." 应转为 None
            mock_redis.set.assert_awaited()

    @pytest.mark.asyncio
    async def test_get_series_observations_empty_observations_returns_warning(self, service):
        """空观测值列表应返回 warning"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"observations": []}
        mock_resp.raise_for_status = MagicMock()
        service.session.get = AsyncMock(return_value=mock_resp)

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("UNKNOWN")
            assert result["status"] == "warning"
            assert result["data"] == []

    @pytest.mark.asyncio
    async def test_get_series_observations_connect_error_returns_error(self, service):
        """网络连接异常应返回 error"""
        service.session.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "无法连接" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_400_invalid_api_key_returns_error(self, service):
        """HTTP 400 且 error_message 含 api_key 应返回 API Key 无效错误"""
        http_err = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        http_err.response.json = MagicMock(return_value={"error_message": "Invalid api_key format"})
        service.session.get = AsyncMock(side_effect=http_err)

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "API Key 无效" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_400_other_returns_error(self, service):
        """HTTP 400 其他错误应返回通用错误"""
        http_err = httpx.HTTPStatusError(
            "400 Bad Request",
            request=MagicMock(),
            response=MagicMock(status_code=400),
        )
        http_err.response.json = MagicMock(side_effect=json.JSONDecodeError("err", "doc", 0))
        service.session.get = AsyncMock(side_effect=http_err)

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "请求参数错误" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_500_returns_error(self, service):
        """HTTP 500 应返回错误"""
        http_err = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        service.session.get = AsyncMock(side_effect=http_err)

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "HTTP 错误" in result["message"]

    @pytest.mark.asyncio
    async def test_get_series_observations_unknown_exception_returns_error(self, service):
        """未知异常应返回 error"""
        service.session.get = AsyncMock(side_effect=RuntimeError("unknown"))

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_series_observations("DGS10")
            assert result["status"] == "error"
            assert "未知异常" in result["message"]

    @pytest.mark.asyncio
    async def test_get_economic_calendar_no_api_key_returns_error(self):
        """未配置 API Key 应返回 error"""
        from backend.services.fred_service import FREDService

        svc = FREDService()
        svc.api_key = None
        result = await svc.get_economic_calendar()
        assert result["status"] == "error"
        assert "API Key" in result["message"]

    @pytest.mark.asyncio
    async def test_get_economic_calendar_cache_hit_returns_cached(self, service):
        """缓存命中应直接返回"""
        cached = {"status": "success", "data": [{"event": "FOMC"}], "source": "fred"}
        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            result = await service.get_economic_calendar()
            assert result == cached

    @pytest.mark.asyncio
    async def test_get_economic_calendar_success_returns_events(self, service):
        """正常路径: 应返回过滤后的事件列表"""
        api_data = {
            "release_dates": [
                {"date": "2099-01-01", "release_name": "Employment Situation"},  # 远未来跳过
                {"date": "2026-06-30", "release_name": "FOMC Meeting"},
                {"date": "2026-06-30", "release_name": ""},  # 空 name 跳过
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_data
        mock_resp.raise_for_status = MagicMock()
        service.session.get = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.services.fred_service.redis_client") as mock_redis,
            patch("backend.services.fred_service.datetime") as mock_dt,
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

    @pytest.mark.asyncio
    async def test_get_economic_calendar_exception_returns_error(self, service):
        """HTTP 异常应返回 error"""
        service.session.get = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("backend.services.fred_service.redis_client") as mock_redis:
            mock_redis.get = AsyncMock(return_value=None)
            result = await service.get_economic_calendar()
            assert result["status"] == "error"
            assert "宏观日历请求异常" in result["message"]

    @pytest.mark.asyncio
    async def test_close_closes_session(self, service):
        """close 应释放底层 AsyncClient"""
        await service.close()
        service.session.aclose.assert_awaited_once()
