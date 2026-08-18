"""
Market Router 补充测试 - 覆盖 /search, /news, /fundamental, /holders 等端点
TEST-18: 提升 market.py 覆盖率
"""

import json
import os
import sys
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.datasource import ErrorInfo, Result, ResultStatus

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.routers.market import router
from backend.routers.market_fundamental import router as fundamental_router

app = FastAPI()
app.include_router(router)
app.include_router(fundamental_router)
client = TestClient(app, raise_server_exceptions=False)


# ─── /market/search ─────────────────────────────────────────────────
class TestSearchTickers:
    @patch("backend.routers.market.ticker_service")
    def test_local_search_success(self, mock_ts):
        mock_ts.search_tickers = AsyncMock(
            return_value={"status": "success", "data": [{"symbol": "AAPL", "name": "Apple"}]}
        )
        resp = client.get("/market/search?q=apple")
        assert resp.status_code == 200
        # BE-13 方案 B: /search 返回扁平 payload {data:[...], source, degraded}
        data = resp.json()
        assert len(data["data"]) == 1

    @patch("backend.routers.market.ticker_service")
    @patch("backend.routers.market.data_service")
    def test_local_empty_yf_fallback(self, mock_ds, mock_ts):
        mock_ts.search_tickers = AsyncMock(return_value={"status": "success", "data": []})
        mock_ds.get_quote = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS, data={"symbol": "AAPL", "name": "Apple"}, source="yfinance"
            )
        )
        resp = client.get("/market/search?q=apple")
        assert resp.status_code == 200

    @patch("backend.routers.market.ticker_service")
    def test_search_error(self, mock_ts):
        mock_ts.search_tickers = AsyncMock(return_value={"status": "error", "message": "搜索失败"})
        resp = client.get("/market/search?q=apple")
        assert resp.status_code == 400


# ─── /market/news ───────────────────────────────────────────────────
class TestGetCompanyNews:
    @patch("backend.routers.market_fundamental.market_data_gateway")
    @patch("backend.routers.market_fundamental.redis_client")
    def test_cache_hit(self, mock_redis, mock_fh):
        import json

        cached = json.dumps({"status": "success", "data": [{"headline": "Test"}]})
        mock_redis.get = AsyncMock(return_value=cached)
        resp = client.get("/market/news?ticker=AAPL")
        assert resp.status_code == 200

    @patch("backend.routers.market_fundamental.market_data_gateway")
    @patch("backend.routers.market_fundamental.redis_client")
    def test_finnhub_success(self, mock_redis, mock_fh):
        # 零幻觉红线：news 已改走 facade/registry 真实源（不再调 market_data_gateway），
        # 测试环境真实源不可用时返回 no_data，严禁 mock 假新闻兜底。
        mock_redis.get = AsyncMock(return_value=None)
        resp = client.get("/market/news?ticker=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_data"

    def test_invalid_ticker(self):
        resp = client.get("/market/news?ticker=")
        assert resp.status_code in [200, 400]


# ─── /market/fundamental/{ticker} ─────────────────────────────────
class TestGetFundamental:
    @patch("backend.routers.market_fundamental.market_data_gateway")
    def test_macro_asset_routing(self, mock_fred):
        """测试宏观资产自动路由到 FRED"""
        mock_fred.get_series_observations = AsyncMock(
            return_value={"status": "success", "data": [{"date": "2024-01-01", "value": 5.0}]}
        )
        resp = client.get("/market/fundamental/US.SPX")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    @patch("backend.routers.market_fundamental.data_service")
    def test_futu_success(self, mock_ds):
        mock_ds.get_fundamental = AsyncMock(
            return_value=Result(status=ResultStatus.SUCCESS, data={"pe": 20.0, "pb": 3.0}, source="futu")
        )
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    @patch("backend.routers.market_fundamental.data_service")
    def test_futu_fail_yf_success(self, mock_ds):
        mock_ds.get_fundamental = AsyncMock(
            return_value=Result(status=ResultStatus.ERROR, error=ErrorInfo(code="FUTU_ERROR", message="失败"))
        )
        mock_ds.get_fundamental_info = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS, data={"shortName": "Apple", "trailingPe": 20.0}, source="yfinance"
            )
        )
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 200


# ─── /market/holders/{ticker} ─────────────────────────────────────
class TestGetTopHolders:
    @patch("backend.routers.market_fundamental.data_service")
    def test_success(self, mock_ds):
        mock_ds.get_hsgt_holders = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS,
                data=[{"holder": "Test", "shares": 1000}],
                source="akshare",
            )
        )
        resp = client.get("/market/holders/HK.00700")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    @patch("backend.routers.market_fundamental.data_service")
    def test_error(self, mock_ds):
        mock_ds.get_hsgt_holders = AsyncMock(
            return_value=Result(status=ResultStatus.ERROR, error=ErrorInfo(code="AK_ERROR", message="失败"))
        )
        resp = client.get("/market/holders/HK.00700")
        assert resp.status_code == 400

    def test_us_ticker_returns_warning(self):
        resp = client.get("/market/holders/US.AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "warning"


# ─── /market/insider-marquee ───────────────────────────────────────
class TestInsiderMarquee:
    # RL-11 修复：端点直接从 Redis ZSET (quant:insider_marquee) 读取，并不依赖
    # market_data_gateway；原测试 mock 错依赖导致真实 redis 调用抛异常 -> 500。
    # 改为整体 mock backend.routers.market.redis_client（与本文件其他用例一致）。
    @patch("backend.routers.market_fundamental.redis_client")
    def test_success(self, mock_rc):
        mock_rc.zrevrange.return_value = [
            json.dumps({"name": "Test", "transactionType": "Buy"}),
            json.dumps({"name": "Test2", "transactionType": "Sell"}),
        ]
        resp = client.get("/market/insider-marquee?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"][0]["name"] == "Test"

    @patch("backend.routers.market_fundamental.redis_client")
    def test_error(self, mock_rc):
        # 端点契约：redis 读取异常时返回 500（无 400 错误态分支）
        mock_rc.zrevrange.side_effect = Exception("redis unreachable")
        resp = client.get("/market/insider-marquee")
        assert resp.status_code == 500
