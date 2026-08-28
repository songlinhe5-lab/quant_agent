"""
Market Router 单元测试
TEST-14: 覆盖 backend/routers/market.py 所有 REST 端点与 WebSocket 处理器
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.services.datasource import ErrorInfo, Result, ResultStatus

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-finnhub-key")
os.environ.setdefault("FRED_API_KEY", "test-fred-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi import FastAPI

from backend.routers.market import router
from backend.routers.market_fundamental import router as fundamental_router

app = FastAPI()
app.include_router(router)
app.include_router(fundamental_router)
client = TestClient(app, raise_server_exceptions=False)


# ─── /market/futu/status ────────────────────────────────────────────────
class TestFutuStatus:
    @patch("backend.routers.market.data_source_router")
    def test_returns_status_and_error(self, mock_ds):
        # 673f99b 后 /futu/status 改走 DataSourceRouter 探活 futu_master 节点,
        # 不再读 legacy market_data_gateway。mock router 使其返回 CONNECTED。
        mock_ds._enabled = True
        mock_ds.fetch_futu = AsyncMock(return_value={"status": "success", "available": True})
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CONNECTED"
        assert data["error"] is None
        assert data["reachable"] is True

    @patch("backend.routers.market.data_source_router")
    def test_disconnected_status(self, mock_ds):
        # 子服务 HEALTH 返回 available=False → DISCONNECTED
        mock_ds._enabled = True
        mock_ds.fetch_futu = AsyncMock(return_value={"status": "success", "available": False})
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISCONNECTED"

    @patch("backend.routers.market.data_source_router")
    def test_router_disabled_status(self, mock_ds):
        # DATA_SOURCE_ROUTER_ENABLED=false → 直接 DISCONNECTED
        mock_ds._enabled = False
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISCONNECTED"

    @patch("backend.routers.market.data_source_router")
    def test_futu_remote_error_status(self, mock_ds):
        # fetch_futu 失败 → 抛异常走 error 分支 → DISCONNECTED
        mock_ds._enabled = True
        mock_ds.fetch_futu = AsyncMock(side_effect=RuntimeError("boom"))
        resp = client.get("/market/futu/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "DISCONNECTED"


# ─── /market/health/services ───────────────────────────────────────────
class TestServicesHealth:
    @patch("backend.routers.market.data_source_router")
    @patch("backend.routers.market.market_data_gateway")
    def test_health_all_healthy(self, mock_md, mock_ds):
        mock_md.is_opend_reachable = MagicMock(return_value=True)
        mock_md.status = "CONNECTED"
        mock_md.error_msg = ""
        mock_md.ak_health_status = MagicMock(return_value={"name": "AKShare", "status": "healthy"})
        mock_md.yf_health_status = MagicMock(return_value={"name": "YFinance", "status": "healthy"})
        mock_ds.get_health_status = AsyncMock(return_value={"status": "healthy"})

        resp = client.get("/market/health/services")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        names = [s["name"] for s in data["data"]]
        assert "Futu OpenD" in names
        assert "AKShare" in names
        assert "YFinance" in names

    @patch("backend.routers.market.data_source_router")
    @patch("backend.routers.market.market_data_gateway")
    def test_futu_disconnected(self, mock_md, mock_ds):
        mock_md.is_opend_reachable = MagicMock(return_value=False)
        mock_md.status = "ERROR"
        mock_md.error_msg = "connection refused"
        mock_md.ak_health_status = MagicMock(return_value={"name": "AKShare", "status": "healthy"})
        mock_md.yf_health_status = MagicMock(return_value={"name": "YFinance", "status": "healthy"})
        mock_ds.get_health_status = AsyncMock(return_value={"status": "healthy"})
        resp = client.get("/market/health/services")
        assert resp.status_code == 200
        data = resp.json()["data"]
        futu_entry = next(s for s in data if s["name"] == "Futu OpenD")
        assert futu_entry["status"] == "disconnected"


# ─── /market/quote ─────────────────────────────────────────────────────
class TestGetQuote:
    @patch("backend.routers.market.data_source_router")
    def test_futu_success(self, mock_ds):
        mock_ds.fetch_futu = AsyncMock(
            return_value={
                "status": "success",
                "data": {"ticker": "US.AAPL", "last_price": 150.0},
                "latency_ms": 10,
                "cached": False,
            }
        )
        resp = client.get("/market/quote?ticker=US.AAPL")
        assert resp.status_code == 200
        body = resp.json()
        # BE-13 方案 B: /quote 返回扁平 payload（含 source/degraded），无外层 status
        assert body["source"] == "futu"
        assert body["last_price"] == 150.0

    @patch("backend.routers.market.data_source_router")
    def test_hk_futu_success(self, mock_ds):
        mock_ds.fetch_futu = AsyncMock(
            return_value={"status": "success", "data": {"last_price": 460.0}, "latency_ms": 8, "cached": False}
        )
        resp = client.get("/market/quote?ticker=HK.00700")
        assert resp.status_code == 200
        assert resp.json()["source"] == "futu"

    @patch("backend.routers.market.data_source_router")
    def test_futu_fail_returns_200(self, mock_ds):
        """上游 Futu 源不可用时属服务端降级：返回 200 + 结构化 error，而非 HTTP 400。
        （HTTP 400 表示客户端请求错误，不应用于描述上游数据源故障）"""
        mock_ds.fetch_futu = AsyncMock(return_value={"status": "error", "message": "数据源超时"})
        resp = client.get("/market/quote?ticker=US.AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert body["code"] == "FUTU_SOURCE_UNAVAILABLE"
        assert body["source"] == "futu"
        assert body["retryable"] is True

    @patch("backend.routers.market._facade_market")
    def test_non_futu_uses_facade(self, mock_facade):
        mock_facade.get_quote = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS,
                data={"last_price": 1.0},
                source="yfinance",
                latency_ms=12,
                cached=False,
            )
        )
        resp = client.get("/market/quote?ticker=BTC-USD")
        assert resp.status_code == 200
        # BE-13 方案 B: /quote 返回扁平 payload，直接读业务字段
        assert resp.json()["last_price"] == 1.0

    @patch("backend.routers.market._facade_market")
    def test_facade_error_returns_200(self, mock_facade):
        """Facade 返回 ERROR 状态时属服务端降级：返回 200 + 结构化 error，而非 HTTP 400。"""
        mock_facade.get_quote = AsyncMock(
            return_value=Result(
                status=ResultStatus.ERROR, error=ErrorInfo(code="TIMEOUT", message="数据源超时"), source="test"
            )
        )
        resp = client.get("/market/quote?ticker=BTC-USD")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "error"
        assert body["code"] == "TIMEOUT"
        assert body["source"] == "test"
        # ErrorInfo 默认 retryable=False，路由透传而非强行覆盖
        assert body["retryable"] is False


# ─── /market/fundamental/{ticker} ─────────────────────────────────────
class TestGetFundamental:
    @patch("backend.routers.market_fundamental.market_data_gateway")
    def test_macro_ticker_routes_to_fred(self, mock_fred):
        mock_fred.get_series_observations = AsyncMock(
            return_value={"status": "success", "data": [{"date": "2024-01-01", "value": "5000"}]}
        )
        resp = client.get("/market/fundamental/SPX")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "fred_series_id" in data["data"]

    @patch("backend.routers.market_fundamental.data_service")
    def test_futu_success(self, mock_ds):
        mock_ds.get_fundamental = AsyncMock(
            return_value=Result(status=ResultStatus.SUCCESS, data={"trailing_PE": 20.0}, source="futu")
        )
        resp = client.get("/market/fundamental/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["data"]["trailing_PE"] == 20.0

    @patch("backend.routers.market_fundamental.data_service")
    def test_etf_returns_warning(self, mock_ds):
        mock_ds.get_fundamental = AsyncMock(
            return_value=Result(status=ResultStatus.ERROR, error=ErrorInfo(code="NOT_SUPPORTED", message="不支持"))
        )
        mock_ds.get_fundamental_info = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS, data={"quoteType": "ETF", "shortName": "SPY ETF"}, source="yfinance"
            )
        )
        resp = client.get("/market/fundamental/US.SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "ETF" in data["message"]

    @patch("backend.routers.market_fundamental.data_service")
    def test_yfinance_stock_fundamentals(self, mock_ds):
        """回归：Futu 失败后降级到 YFinance 个股基本面 (Result 对象 API)"""
        mock_ds.get_fundamental = AsyncMock(
            return_value=Result(status=ResultStatus.ERROR, error=ErrorInfo(code="NOT_SUPPORTED", message="不支持"))
        )
        mock_ds.get_fundamental_info = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS,
                data={
                    "quoteType": "EQUITY",
                    "shortName": "ProShares S&P 500 Ex-Health Care",
                    "trailingPe": 18.5,
                    "returnOnEquity": 0.1234,
                    "shortRatio": 2.1,
                },
                source="yfinance",
            )
        )
        resp = client.get("/market/fundamental/US.SPCX")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["data"]["trailing_PE"] == 18.5
        assert data["data"]["ROE"] == "12.34%"


# ─── /market/news ───────────────────────────────────────────────────────
class TestGetCompanyNews:
    @patch("backend.routers.market_fundamental.redis_client")
    @patch("backend.routers.market_fundamental.market_data_gateway")
    def test_cached_result(self, mock_finhub, mock_redis):
        import json

        cached = json.dumps({"status": "success", "data": [{"headline": "Cached"}]})
        mock_redis.get = AsyncMock(return_value=cached)
        resp = client.get("/market/news?ticker=AAPL&limit=5")
        assert resp.status_code == 200
        assert resp.json()["data"][0]["headline"] == "Cached"

    @patch("backend.routers.market_fundamental.redis_client")
    @patch("backend.routers.market_fundamental.market_data_gateway")
    def test_fetch_from_finnhub(self, mock_finhub, mock_redis):
        # 零幻觉红线：news 已改走 facade/registry 真实源（不再调 market_data_gateway），
        # 测试环境真实源不可用时返回 no_data，严禁 mock 假新闻兜底。
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        resp = client.get("/market/news?ticker=AAPL&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_data"

    def test_invalid_ticker(self):
        resp = client.get("/market/news?ticker=###&limit=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"


# ─── /market/search ────────────────────────────────────────────────────
class TestSearchTickers:
    @patch("backend.routers.market.ticker_service")
    def test_local_search_success(self, mock_ticker_svc):
        mock_ticker_svc.search_tickers = AsyncMock(
            return_value={"status": "success", "data": [{"ticker": "AAPL", "name": "Apple"}]}
        )
        resp = client.get("/market/search?q=apple")
        assert resp.status_code == 200
        # BE-13 方案 B: /search 返回扁平 payload {data:[...], source, degraded}
        assert len(resp.json()["data"]) == 1

    @patch("backend.routers.market.ticker_service")
    @patch("backend.routers.market.data_service")
    def test_local_empty_fallback_to_yf(self, mock_ds, mock_ticker_svc):
        mock_ticker_svc.search_tickers = AsyncMock(return_value={"status": "success", "data": []})
        mock_ds.get_quote = AsyncMock(
            return_value=Result(
                status=ResultStatus.SUCCESS, data={"symbol": "AAPL", "name": "Apple"}, source="yfinance"
            )
        )
        resp = client.get("/market/search?q=AAPL")
        assert resp.status_code == 200


# ─── /market/holders/{ticker} ─────────────────────────────────────────
class TestGetTopHolders:
    def test_us_ticker_returns_warning(self):
        resp = client.get("/market/holders/US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["status"] == "warning"

    @patch("backend.routers.market_fundamental.data_service")
    def test_hk_ticker_calls_akshare(self, mock_ds):
        mock_ds.get_hsgt_holders = AsyncMock(
            return_value=Result(status=ResultStatus.SUCCESS, data=[], source="akshare")
        )
        resp = client.get("/market/holders/HK.00700")
        assert resp.status_code == 200


# ─── /market/insider-marquee ───────────────────────────────────────────
class TestInsiderMarquee:
    @patch("backend.routers.market_fundamental.redis_client")
    def test_returns_success(self, mock_redis):
        import json

        mock_redis.zrevrange = AsyncMock(return_value=[json.dumps({"ticker": "AAPL", "transaction": "BUY"})])
        resp = client.get("/market/insider-marquee?limit=5")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


# ─── /market/kline/sync ────────────────────────────────────────────────
class TestSyncKlineWarehouse:
    @patch("backend.routers.market.kline_warehouse")
    def test_sync_success(self, mock_wh):
        mock_wh.update_ticker = AsyncMock(return_value=True)
        resp = client.post("/market/kline/sync", json={"ticker": "US.AAPL", "interval": "1d"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    @patch("backend.routers.market.kline_warehouse")
    def test_sync_failure_returns_500(self, mock_wh):
        mock_wh.update_ticker = AsyncMock(return_value=False)
        resp = client.post("/market/kline/sync", json={"ticker": "US.AAPL", "interval": "1d"})
        assert resp.status_code == 500


# ─── /market/option-iv-summary ──────────────────────────────────────────────
class TestOptionIvSummary:
    @patch("backend.routers.market._facade_market")
    def test_success_envelope(self, mock_facade):
        # 业务方法返回扁平 dict（含 available 标记），路由包入 data 信封
        mock_facade.get_option_iv_summary = AsyncMock(
            return_value={
                "ticker": "US.AAPL",
                "atm_iv": 0.382,
                "iv_percentile": 0.64,
                "rv30d": 0.315,
                "skew": 2.1,
                "available": True,
            }
        )
        resp = client.get("/market/option-iv-summary?ticker=US.AAPL")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        data = body["data"]
        assert data["atm_iv"] == 0.382
        assert data["iv_percentile"] == 0.64
        assert data["skew"] == 2.1

    @patch("backend.routers.market._facade_market")
    def test_degraded_when_unavailable(self, mock_facade):
        # 底层不可用时 available=False → 路由标记 degraded=True，不 500
        mock_facade.get_option_iv_summary = AsyncMock(
            return_value={
                "ticker": "US.AAPL",
                "atm_iv": None,
                "iv_percentile": None,
                "rv30d": None,
                "skew": None,
                "available": False,
            }
        )
        resp = client.get("/market/option-iv-summary?ticker=US.AAPL")
        assert resp.status_code == 200
        assert resp.json()["degraded"] is True
