"""
行情路由增强单元测试
覆盖: backend/routers/market.py 中未在 test_market.py 覆盖的端点
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


def _unwrap(resp):
    """剥离统一响应封装，返回路由原始 dict"""
    body = resp.json()
    return body.get("data", body)


class TestMarketFutuStatusRoutes:
    """Futu 连接状态路由测试"""

    @patch("backend.routers.market.futu_service")
    def test_get_futu_status_success(self, mock_futu):
        """正常路径：获取 Futu 连接状态"""
        mock_futu.status = "CONNECTED"
        mock_futu.error_msg = ""
        client = TestClient(app)
        resp = client.get("/api/v1/market/futu/status")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "CONNECTED"


class TestMarketServicesHealthRoutes:
    """数据源健康检查路由测试"""

    @patch("backend.routers.market.yf_service")
    @patch("backend.routers.market.akshare_service")
    def test_get_services_health_success(self, mock_akshare, mock_yf):
        """正常路径：获取所有数据源健康状态"""
        mock_akshare.get_health_status = MagicMock(
            return_value={"name": "AKShare", "status": "healthy", "cooldown_remaining": 0, "message": "正常"}
        )
        mock_yf.get_health_status = MagicMock(
            return_value={"name": "YFinance", "status": "healthy", "cooldown_remaining": 0, "message": "正常"}
        )
        client = TestClient(app)
        resp = client.get("/api/v1/market/health/services")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 2


class TestMarketFundFlowRoutes:
    """资金流路由测试"""

    @patch("backend.routers.market.futu_service")
    def test_get_fund_flow_success(self, mock_futu):
        """正常路径：获取资金流数据"""
        mock_futu.get_fund_flow = AsyncMock(
            return_value={"status": "success", "data": [{"date": "2026-01-01", "net_inflow": 1000000}]}
        )
        client = TestClient(app)
        resp = client.get("/api/v1/market/fund-flow?ticker=HK.00700")
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"

    @patch("backend.routers.market.futu_service")
    def test_get_fund_flow_failure(self, mock_futu):
        """异常路径：Futu 接口失败返回 400"""
        mock_futu.get_fund_flow = AsyncMock(return_value={"status": "error", "message": "标的暂不支持"})
        client = TestClient(app)
        resp = client.get("/api/v1/market/fund-flow?ticker=US.AAPL")
        assert resp.status_code == 400


class TestMarketSearchRoutes:
    """股票代码搜索路由测试"""

    @patch("backend.routers.market.ticker_service")
    def test_search_tickers_success(self, mock_ticker_svc):
        """正常路径：本地词库命中"""
        mock_ticker_svc.search_tickers = AsyncMock(
            return_value={
                "status": "success",
                "data": [{"code": "HK.00700", "name": "腾讯控股"}],
            }
        )
        client = TestClient(app)
        resp = client.get("/api/v1/market/search?q=00700")
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"


class TestMarketHoldersRoutes:
    """机构持仓路由测试"""

    @patch("backend.routers.market.akshare_service")
    def test_get_holders_us_ticker_warning(self, mock_akshare):
        """参数路径：美股标的直接返回 warning"""
        client = TestClient(app)
        resp = client.get("/api/v1/market/holders/US.AAPL")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "warning"

    @patch("backend.routers.market.data_source_router")
    def test_get_holders_hk_ticker_success(self, mock_router):
        """正常路径：获取港股机构持仓"""
        mock_router.fetch_akshare = AsyncMock(return_value={"status": "success", "data": [{"holder": "中投"}]})
        client = TestClient(app)
        resp = client.get("/api/v1/market/holders/HK.00700")
        assert resp.status_code == 200
        assert _unwrap(resp)["status"] == "success"


class TestMarketInsiderMarqueeRoutes:
    """内幕交易跑马灯路由测试"""

    @patch("backend.routers.market.redis_client")
    def test_get_insider_marquee_success(self, mock_redis):
        """正常路径：从 Redis ZSET 获取跑马灯数据"""
        import json

        mock_redis.zrevrange = AsyncMock(return_value=[json.dumps({"ticker": "AAPL", "owner": "CEO"})])
        client = TestClient(app)
        resp = client.get("/api/v1/market/insider-marquee?limit=5")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["data"]) == 1

    @patch("backend.routers.market.redis_client")
    def test_get_insider_marquee_empty(self, mock_redis):
        """空数据路径：ZSET 为空时返回空列表"""
        mock_redis.zrevrange = AsyncMock(return_value=[])
        client = TestClient(app)
        resp = client.get("/api/v1/market/insider-marquee")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["data"] == []


class TestMarketKlineSyncRoutes:
    """K 线数据同步路由测试"""

    @patch("backend.routers.market.kline_warehouse")
    def test_sync_kline_success(self, mock_warehouse):
        """正常路径：K 线数据同步成功"""
        mock_warehouse.update_ticker = AsyncMock(return_value=True)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/market/kline/sync",
            json={"ticker": "HK.00700", "interval": "1d", "force_full": False},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.market.kline_warehouse")
    def test_sync_kline_failure(self, mock_warehouse):
        """异常路径：K 线数据同步失败返回 500"""
        mock_warehouse.update_ticker = AsyncMock(return_value=False)
        client = TestClient(app)
        resp = client.post(
            "/api/v1/market/kline/sync",
            json={"ticker": "HK.00700", "interval": "1d"},
        )
        assert resp.status_code == 500

    def test_sync_kline_invalid_payload(self):
        """参数校验：缺少 ticker 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/market/kline/sync", json={})
        assert resp.status_code == 422
