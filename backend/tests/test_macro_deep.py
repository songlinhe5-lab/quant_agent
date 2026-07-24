"""
Macro 路由深度测试 - 覆盖 dashboard/assets/margin 端点
覆盖: backend/routers/macro.py (lines 696-812, 818-900, 1170-1192)
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


def _unwrap(resp):
    """剥离 response_envelope_middleware 封装"""
    body = resp.json()
    if isinstance(body, dict) and "code" in body and "data" in body:
        return body["data"]
    return body


# ==========================================
# GET /macro/dashboard
# ==========================================
class TestMacroDashboard:
    @patch("backend.routers.macro.redis_client")
    def test_dashboard_cached(self, mock_redis, client):
        """缓存命中"""
        cached_data = {"status": "success", "data": {"macroAssets": []}}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_data))

        resp = client.get("/api/v1/macro/dashboard")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.macro._fetch_sector_fund_flow")
    @patch("backend.routers.macro._fetch_margin_trading_data")
    @patch("backend.routers.macro._fetch_earnings_calendar_data")
    @patch("backend.routers.macro.get_macro_news")
    @patch("backend.routers.macro._fetch_macro_calendar_data")
    @patch("backend.routers.macro.get_macro_assets")
    @patch("backend.routers.macro.redis_client")
    def test_dashboard_fresh(
        self, mock_redis, mock_assets, mock_calendar, mock_news, mock_earnings, mock_margin, mock_sector_flow, client
    ):
        """强制刷新"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_assets.return_value = {
            "status": "success",
            "data": {
                "radarData": [{"name": "test"}],
                "macroAssets": [{"symbol": "SPX"}],
                "sentimentIndicators": {"vix": 15},
            },
        }
        mock_calendar.return_value = {"status": "success", "data": [{"event": "FOMC"}]}
        mock_news.return_value = {"status": "success", "data": [{"headline": "test"}]}
        mock_earnings.return_value = {"status": "success", "data": [{"symbol": "AAPL"}]}
        mock_margin.return_value = {"status": "success", "data": [{"market": "US"}]}
        mock_sector_flow.return_value = {"status": "success", "data": {}}

        resp = client.get("/api/v1/macro/dashboard?force_refresh=true")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "macroAssets" in data["data"]

    @patch("backend.routers.macro._fetch_sector_fund_flow")
    @patch("backend.routers.macro._fetch_margin_trading_data")
    @patch("backend.routers.macro._fetch_earnings_calendar_data")
    @patch("backend.routers.macro.get_macro_news")
    @patch("backend.routers.macro._fetch_macro_calendar_data")
    @patch("backend.routers.macro.get_macro_assets")
    @patch("backend.routers.macro.redis_client")
    def test_dashboard_with_exceptions(
        self, mock_redis, mock_assets, mock_calendar, mock_news, mock_earnings, mock_margin, mock_sector_flow, client
    ):
        """部分数据源异常"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()

        mock_assets.return_value = {"status": "error"}
        mock_calendar.return_value = Exception("timeout")
        mock_news.return_value = {"status": "success", "data": []}
        mock_earnings.return_value = Exception("fail")
        mock_margin.return_value = Exception("fail")
        mock_sector_flow.return_value = Exception("fail")

        resp = client.get("/api/v1/macro/dashboard?force_refresh=true")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"


# ==========================================
# GET /macro/margin-trading
# ==========================================
class TestMarginTrading:
    @patch("backend.services.margin.service.margin_service")
    def test_margin_success(self, mock_margin_svc, client):
        """融资融券数据获取成功"""
        mock_margin_svc.get_all_margin_data = AsyncMock(
            return_value={"status": "success", "data": [{"market": "A股", "balance": 1.5e12}]}
        )
        resp = client.get("/api/v1/macro/margin-trading")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.services.margin.service.margin_service")
    def test_margin_error(self, mock_margin_svc, client):
        """融资融券数据获取失败"""
        mock_margin_svc.get_all_margin_data = AsyncMock(side_effect=Exception("API down"))
        resp = client.get("/api/v1/macro/margin-trading")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"


# ==========================================
# GET /macro/assets
# ==========================================
class TestMacroAssets:
    @patch("backend.routers.macro.redis_client")
    def test_assets_cached(self, mock_redis, client):
        """资产数据缓存命中"""
        cached = {"status": "success", "data": {"macroAssets": [], "radarData": [], "sentimentIndicators": {}}}
        mock_redis.get = AsyncMock(return_value=json.dumps(cached))

        resp = client.get("/api/v1/macro/assets")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.macro._fetch_macro_assets_data")
    @patch("backend.routers.macro.redis_client")
    def test_assets_fresh(self, mock_redis, mock_fetch, client):
        """资产数据强制刷新"""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock()
        mock_fetch.return_value = [{"symbol": "SPX", "name": "S&P 500", "value": 5000, "change": 0.5}]

        resp = client.get("/api/v1/macro/assets?force_refresh=true")
        assert resp.status_code == 200


# ==========================================
# _fetch_macro_assets_data 内部函数
# ==========================================
class TestFetchMacroAssetsData:
    @pytest.mark.asyncio
    @patch("backend.routers.macro.redis_client")
    async def test_fetch_assets_from_cache(self, mock_redis):
        """从 Redis 缓存获取资产数据"""
        from backend.routers.macro import _fetch_macro_assets_data

        # 模拟 Redis 中有缓存数据
        records = [
            {"Close": 5000.0, "Open": 4990.0, "Date": "2024-07-01"},
            {"Close": 5010.0, "Open": 5000.0, "Date": "2024-07-02"},
        ]
        mock_redis.get = AsyncMock(return_value=json.dumps(records))

        result = await _fetch_macro_assets_data()
        assert isinstance(result, list)
        assert len(result) > 0
        assert result[0]["symbol"] == "SPX"
        assert result[0]["value"] == 5010.0

    @pytest.mark.asyncio
    @patch("backend.routers.macro.redis_client")
    async def test_fetch_assets_no_cache(self, mock_redis):
        """无缓存数据"""
        from backend.routers.macro import _fetch_macro_assets_data

        mock_redis.get = AsyncMock(return_value=None)

        result = await _fetch_macro_assets_data()
        assert isinstance(result, list)
        # 无缓存时返回空列表或兜底数据
        assert len(result) == 0 or all("symbol" in item for item in result)


# ==========================================
# GET /macro/sentiment
# ==========================================
class TestMacroSentiment:
    def test_sentiment_history(self, client):
        """情绪历史数据"""
        mock_record = MagicMock()
        mock_record.timestamp = None
        mock_record.pc_ratio = 0.8
        mock_record.vix_value = 15.0
        mock_record.credit_spread = 3.2
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = [mock_record]
        mock_db.query.return_value = mock_query
        from backend.core.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = client.get("/api/v1/macro/sentiment-history")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200


# ==========================================
# GET /macro/news
# ==========================================
class TestMacroNews:
    @patch("backend.routers.macro.redis_client")
    def test_news_from_cache(self, mock_redis, client):
        """新闻缓存"""
        cached_news = [
            {"headline": "Fed cuts rates", "datetime": 1700000000, "summary": "test"},
        ]
        mock_redis.zrevrange = AsyncMock(return_value=[json.dumps(n) for n in cached_news])

        resp = client.get("/api/v1/macro/news")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.macro.redis_client")
    def test_news_empty(self, mock_redis, client):
        """无新闻"""
        mock_redis.zrevrange = AsyncMock(return_value=[])

        resp = client.get("/api/v1/macro/news")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"] == [] or isinstance(data["data"], list)
