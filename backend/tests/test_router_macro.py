"""routers/macro.py 单元测试

覆盖: calendar / series / sentiment-history / capital-flow / news / dashboard / assets
"""

import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ==========================================
# GET /api/v1/macro/calendar
# ==========================================


class TestMacroCalendar:
    def test_calendar_cache_hit_returns_cached(self, client):
        """缓存命中:直接返回 Redis 缓存数据"""
        cached = {"status": "success", "data": [{"event": "Fed", "date": "2026-06-29T00:00:00Z"}]}
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/macro/calendar?days_ahead=7")
        assert resp.status_code == 200
        body = resp.json()
        # 全局响应封装: {"code":0,"data":{...}} 或直接返回
        data = body.get("data", body)
        assert data["status"] == "success"

    def test_calendar_akshare_success(self, client):
        """AkShare 正常返回:时区转换 + 高危关键词识别"""
        with (
            patch("backend.routers.macro.redis_client") as m_redis,
            patch("backend.routers.macro.market_data") as m_ak,
            patch("backend.routers.macro.llm_service") as m_llm,
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            m_redis.setex = AsyncMock(return_value=True)
            m_ak.get_economic_calendar_ak = AsyncMock(
                return_value={
                    "status": "success",
                    "source": "jin10",
                    "data": [
                        {
                            "event": "FOMC Rate Decision",
                            "time": "2026-06-29 02:00:00",
                            "country": "US",
                            "impact": "medium",
                            "previous": "4.5",
                            "estimate": "4.5",
                            "actual": "",
                        }
                    ],
                }
            )
            # LLM 推演 mock
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(
                return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="鹰派信号"))])
            )
            m_llm.get_client.return_value = mock_client
            m_llm.get_model.return_value = "gpt-4o"
            resp = client.get("/api/v1/macro/calendar?days_ahead=7")
        assert resp.status_code == 200
        data = resp.json().get("data", resp.json())
        assert data["status"] == "success"
        assert len(data["data"]) == 1
        # FOMC 关键词应被识别为 high
        assert data["data"][0]["impact"] == "high"

    def test_calendar_fallback_to_mock_when_all_sources_fail(self, client):
        """所有数据源失败:返回 500 错误"""
        with (
            patch("backend.routers.macro.redis_client") as m_redis,
            patch("backend.routers.macro.market_data") as m_ak,
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            m_ak.get_economic_calendar_ak = AsyncMock(return_value={"status": "error"})
            m_ak.get_economic_calendar = AsyncMock(return_value={"status": "error"})
            resp = client.get("/api/v1/macro/calendar?days_ahead=7")
        assert resp.status_code == 500

    def test_calendar_invalid_days_param_returns_422(self, client):
        """参数校验:days_ahead 超出 [1,30] 范围返回 422"""
        resp = client.get("/api/v1/macro/calendar?days_ahead=100")
        assert resp.status_code == 422


# ==========================================
# GET /api/v1/macro/series
# ==========================================


class TestMacroSeries:
    def test_series_success(self, client):
        with patch("backend.routers.macro.market_data") as m_fred:
            m_fred.get_series_observations = AsyncMock(
                return_value={
                    "status": "success",
                    "data": [{"date": "2026-01", "value": 4.5}],
                }
            )
            resp = client.get("/api/v1/macro/series?series_id=DGS10&limit=10")
        assert resp.status_code == 200

    def test_series_error_returns_400(self, client):
        with patch("backend.routers.macro.market_data") as m_fred:
            m_fred.get_series_observations = AsyncMock(
                return_value={
                    "status": "error",
                    "message": "invalid series",
                }
            )
            resp = client.get("/api/v1/macro/series?series_id=INVALID")
        assert resp.status_code == 400


# ==========================================
# GET /api/v1/macro/sentiment-history
# ==========================================


class TestSentimentHistory:
    def test_sentiment_history_no_model_returns_500(self, client):
        """models 无 SentimentRecord 属性时返回 500"""
        with patch("backend.routers.macro.models") as m_models:
            m_models.SentimentRecord = None
            # hasattr 返回 False
            resp = client.get("/api/v1/macro/sentiment-history")
        assert resp.status_code == 500

    def test_sentiment_history_returns_records(self, client):
        """有记录时返回格式化列表"""
        from backend.core import models

        if not hasattr(models, "SentimentRecord"):
            pytest.skip("SentimentRecord 模型未定义")
        mock_record = MagicMock()
        mock_record.timestamp = None
        mock_record.pc_ratio = 0.9
        mock_record.vix_value = 15.0
        mock_record.credit_spread = 3.5
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = [mock_record]
        mock_db.query.return_value = mock_query
        from backend.core.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = client.get("/api/v1/macro/sentiment-history?limit=10")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200


# ==========================================
# GET /api/v1/macro/capital-flow
# ==========================================


class TestCapitalFlow:
    def test_capital_flow_cache_hit(self, client):
        """缓存命中:直接返回"""
        cached = {"status": "success", "data": [{"market": "HK", "amount": 10.5}]}
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/macro/capital-flow")
        assert resp.status_code == 200

    @pytest.mark.xfail(reason="_fetch_capital_flows 未实现", strict=False)
    def test_capital_flow_fetches_from_sources(self, client):
        """缓存未命中:从 AkShare + Futu 聚合"""
        with (
            patch("backend.routers.macro.redis_client") as m_redis,
            patch("backend.routers.macro.market_data") as m_ak,
            patch("backend.routers.macro.market_data") as m_futu,
            patch("backend.routers.macro.manager") as m_manager,
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            m_ak.get_southbound_flow = AsyncMock(
                return_value={
                    "status": "success",
                    "data": {"net_inflow": 50.5, "sparkline": [1, -1, 1]},
                }
            )
            m_futu.get_fund_flow = AsyncMock(
                return_value={
                    "status": "success",
                    "data": {"main_fund_net_inflow": 200_000_000},
                }
            )
            # manager.flow_cache 为空,触发 futu 调用
            m_manager.flow_cache = {}
            resp = client.get("/api/v1/macro/capital-flow")
        assert resp.status_code == 200
        data = resp.json().get("data", resp.json())
        assert data["status"] == "success"
        assert len(data["data"]) > 0


# ==========================================
# GET /api/v1/macro/news
# ==========================================


class TestMacroNews:
    def test_news_general_from_redis_stream(self, client):
        """general 分类:从 Redis ZSET 读取"""
        news_item = json.dumps({"headline": "Fed cuts rates", "datetime": 1719500000})
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.zrevrange = AsyncMock(return_value=[news_item])
            resp = client.get("/api/v1/macro/news?category=general&limit=5")
        assert resp.status_code == 200
        data = resp.json().get("data", resp.json())
        assert data["status"] == "success"
        assert len(data["data"]) == 1

    def test_news_non_general_delegates_to_finnhub(self, client):
        """非 general 分类:直接走 Finnhub"""
        with patch("backend.routers.macro.market_data") as m_finnhub:
            m_finnhub.get_market_news = AsyncMock(
                return_value={
                    "status": "success",
                    "data": [{"headline": "crypto news"}],
                }
            )
            resp = client.get("/api/v1/macro/news?category=crypto")
        assert resp.status_code == 200
        m_finnhub.get_market_news.assert_awaited_once()

    def test_news_empty_redis_falls_back_to_finnhub(self, client):
        """Redis 空时回退 Finnhub"""
        with (
            patch("backend.routers.macro.redis_client") as m_redis,
            patch("backend.routers.macro.market_data") as m_finnhub,
        ):
            m_redis.zrevrange = AsyncMock(return_value=[])
            m_finnhub.get_market_news = AsyncMock(
                return_value={
                    "status": "success",
                    "data": [{"headline": "fallback news"}],
                }
            )
            resp = client.get("/api/v1/macro/news?category=general")
        assert resp.status_code == 200
        m_finnhub.get_market_news.assert_awaited_once()


# ==========================================
# GET /api/v1/macro/assets
# ==========================================


class TestMacroAssets:
    def test_assets_cache_hit(self, client):
        cached = {"status": "success", "data": {"macroAssets": [], "radarData": []}}
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/macro/assets")
        assert resp.status_code == 200

    def test_assets_force_refresh_bypasses_cache(self, client):
        """force_refresh=True 绕过缓存"""
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            resp = client.get("/api/v1/macro/assets?force_refresh=true")
        assert resp.status_code == 200


# ==========================================
# GET /api/v1/macro/dashboard
# ==========================================


class TestMacroDashboard:
    def test_dashboard_cache_hit(self, client):
        cached = {"status": "success", "data": {"macroAssets": []}}
        with patch("backend.routers.macro.redis_client") as m_redis:
            m_redis.get = AsyncMock(return_value=json.dumps(cached))
            resp = client.get("/api/v1/macro/dashboard")
        assert resp.status_code == 200

    def test_dashboard_aggregates_all_sources(self, client):
        """缓存未命中:并发聚合所有数据源"""
        with (
            patch("backend.routers.macro.redis_client") as m_redis,
            patch("backend.routers.macro.get_macro_assets", new_callable=AsyncMock) as m_assets,
            patch("backend.routers.macro._fetch_macro_calendar_data", new_callable=AsyncMock) as m_cal,
            patch("backend.routers.macro.get_macro_news", new_callable=AsyncMock) as m_news,
            patch("backend.routers.macro._fetch_earnings_calendar_data", new_callable=AsyncMock) as m_earn,
        ):
            m_redis.get = AsyncMock(return_value=None)
            m_redis.set = AsyncMock(return_value=True)
            m_assets.return_value = {
                "status": "success",
                "data": {"radarData": [], "macroAssets": [], "sentimentIndicators": {}},
            }
            m_cal.return_value = {"status": "success", "data": []}
            m_news.return_value = {"status": "success", "data": []}
            m_earn.return_value = {"status": "success", "data": []}
            resp = client.get("/api/v1/macro/dashboard")
        assert resp.status_code == 200
        data = resp.json().get("data", resp.json())
        assert data["status"] == "success"
        assert "macroAssets" in data["data"]
