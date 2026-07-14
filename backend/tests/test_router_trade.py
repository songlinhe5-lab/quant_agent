"""routers/trade.py 单元测试

覆盖: place_order 风控拦截/通过/STATUS/CANCEL/缓存命中/ATR降杠杆,
get_account_info, get_portfolio, get_trades DB 查询。
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
from backend.routers import trade as trade_module


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_trade_locks():
    """每个测试后清理 _trade_locks 防止跨测试污染"""
    yield
    trade_module._trade_locks.clear()


def _setup_redis_mock(prefs=None, account_cache=None):
    """构造 redis_client mock,prefs 为杠杆偏好,account_cache 为账户缓存"""
    m_redis = AsyncMock()
    pref_data = json.dumps(prefs or {}) if prefs else None
    acc_data = json.dumps(account_cache) if account_cache else None

    async def _get(key):
        if key.endswith(":preferences"):
            return pref_data
        if key.endswith(":account_info"):
            return acc_data
        return None

    m_redis.get = AsyncMock(side_effect=_get)
    m_redis.set = AsyncMock(return_value=True)
    return m_redis


class TestPlaceOrderRiskControl:
    """place_order 核心风控逻辑"""

    def test_buy_blocked_when_order_value_exceeds_leverage_limit(self, client):
        """风控拦截:订单总价值超过最大杠杆限制 → 403"""
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 10000.0})
            # ATR 测算跳过(避免真实调用 yfinance)
            m_yf.get_tech_indicators = AsyncMock(return_value={"status": "error"})
            # 订单价值 100*200=20000 > 10000*1.0 → 拦截
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 100, "price": 200.0},
            )
        assert resp.status_code == 403
        # 风控拦截返回 HTTPException，被异常处理器包装
        body = resp.json()
        assert body["code"] == int(403)  # HTTPException 的 status_code
        assert "风控拦截" in body["msg"]

    def test_buy_success_when_within_leverage_limit(self, client):
        """风控通过:订单价值 ≤ 最大杠杆限制 → 下单成功"""
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 2.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.place_order = AsyncMock(return_value={"status": "success", "order_id": "ord-1"})
            m_yf.get_tech_indicators = AsyncMock(
                return_value={"status": "error"}  # ATR 测算跳过
            )
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 10, "price": 100.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        # 响应被包装成统一格式 {"code": 0, "data": {...}, "msg": "...", "ts": ...}
        assert body["code"] == 0
        # 端点返回 {"status": "success", "order_id": "ord-1"}
        # 所以 body["data"] 包含端点的原始响应
        assert body["data"]["status"] == "success"
        m_futu.place_order.assert_called_once()

    def test_account_cache_hit_avoids_futu_api_call(self, client):
        """账户缓存命中:不调用 futu_service.get_account_info"""
        cached_acc = {"status": "success", "total_assets": 50000.0}
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0}, account_cache=cached_acc)
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
        ):
            m_futu.get_account_info = AsyncMock()
            m_futu.place_order = AsyncMock(return_value={"status": "success", "order_id": "ord-2"})
            m_yf.get_tech_indicators = AsyncMock(return_value={"status": "error"})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "HK.00700", "action": "BUY", "qty": 5, "price": 300.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        m_futu.get_account_info.assert_not_awaited()

    def test_futu_account_error_raises_500(self, client):
        """Futu 账户接口返回 error → 500"""
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "error", "message": "futu down"})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 1, "price": 10.0},
            )
        assert resp.status_code == 500

    def test_atr_high_volatility_forces_deleverage(self, client):
        """ATR 波动率 >5% 强制降杠杆至 1.0x"""
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 3.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
            patch("backend.routers.trade._to_yf_ticker", return_value="AAPL"),
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.place_order = AsyncMock(return_value={"status": "success", "order_id": "ord-3"})
            # ATR_14=10, price=100 → volatility=10% > 5% → 降杠杆
            m_yf.get_tech_indicators = AsyncMock(
                return_value={
                    "status": "success",
                    "data": {"trend": [{"ATR_14": 10.0}]},
                }
            )
            # 订单价值 100*100=10000, 降杠杆后上限 100000*1.0=100000 → 通过
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 100, "price": 100.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        # 响应被包装成统一格式，risk_control 在 body["data"] 中
        assert "risk_control" in body["data"]
        assert "suggested_stop_loss" in body["data"]["risk_control"]

    def test_atr_exception_swallowed_and_order_proceeds(self, client):
        """ATR 测算异常被吞,不影响下单"""
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade._to_yf_ticker", side_effect=Exception("yf err")),
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.place_order = AsyncMock(return_value={"status": "success", "order_id": "ord-4"})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 10, "price": 100.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0


class TestPlaceOrderActions:
    """place_order 的 STATUS/CANCEL/SELL 动作"""

    def test_status_action_queries_existing_order(self, client):
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.query_order = AsyncMock(return_value={"status": "success", "order": {"id": "ord-x"}})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "STATUS", "qty": 0, "price": 0, "order_id": "ord-x"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        m_futu.query_order.assert_awaited_once()

    def test_cancel_action_modifies_order(self, client):
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.cancel_order = AsyncMock(return_value={"status": "success", "cancelled": True})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "CANCEL", "qty": 0, "price": 0, "order_id": "ord-y"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        m_futu.cancel_order.assert_awaited_once()

    def test_sell_action_uses_trd_side_sell(self, client):
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.place_order = AsyncMock(return_value={"status": "success", "order_id": "ord-sell"})
            m_yf.get_tech_indicators = AsyncMock(return_value={"status": "error"})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "SELL", "qty": 10, "price": 100.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        m_futu.place_order.assert_called_once()

    def test_futu_place_order_error_returns_400(self, client):
        m_redis = _setup_redis_mock(prefs={"defaultLeverage": 1.0})
        with (
            patch("backend.routers.trade.redis_client", m_redis),
            patch("backend.routers.trade.broker") as m_futu,
            patch("backend.routers.trade.market_data") as m_yf,
        ):
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 100000.0})
            m_futu.place_order = AsyncMock(return_value={"status": "error", "message": "market closed"})
            m_yf.get_tech_indicators = AsyncMock(return_value={"status": "error"})
            resp = client.post(
                "/api/v1/trade/order",
                json={"ticker": "US.AAPL", "action": "BUY", "qty": 1, "price": 10.0},
            )
        assert resp.status_code == 400


class TestAccountAndPortfolio:
    """get_account_info + get_portfolio"""

    def test_get_account_info_success(self, client):
        with patch("backend.routers.trade.broker") as m_futu:
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 999.0})
            resp = client.get("/api/v1/trade/account?market=HK")
        assert resp.status_code == 200
        body = resp.json()
        # 响应被包装成统一格式
        assert body["code"] == 0
        assert body["data"]["total_assets"] == 999.0

    def test_get_account_info_error_returns_400(self, client):
        with patch("backend.routers.trade.broker") as m_futu:
            m_futu.get_account_info = AsyncMock(return_value={"status": "error", "message": "timeout"})
            resp = client.get("/api/v1/trade/account")
        assert resp.status_code == 400

    def test_get_portfolio_returns_risk_metrics(self, client):
        with patch("backend.routers.trade.broker") as m_futu:
            m_futu.get_account_info = AsyncMock(return_value={"status": "success", "total_assets": 50000.0})
            resp = client.get("/api/v1/trade/portfolio")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        # GET /portfolio 返回 {"status": "success", "data": {"base_nav": ..., ...}}
        # 所以 body["data"]["data"]["base_nav"] 是实际的值
        assert body["data"]["data"]["base_nav"] == 50000.0
        assert "sharpe" in body["data"]["data"]
        assert "max_dd" in body["data"]["data"]


class TestGetTrades:
    """get_trades DB 查询"""

    def test_get_trades_returns_empty_list(self, client):
        """空表返回空列表"""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        mock_db.query.return_value = mock_query

        from backend.core.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = client.get("/api/v1/trade/trades?limit=10")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()["data"]  # 响应被包装成 {"code": 0, "data": [...]}
        assert data == []

    def test_get_trades_returns_logged_trades(self, client):
        """有交易记录时返回格式化列表"""
        mock_log = MagicMock(
            id=1,
            timestamp=__import__("datetime").datetime(2026, 1, 1),
            ticker="US.AAPL",
            action="BUY",
            price=150.0,
            qty=10,
            status="FILLED",
            message="ok",
        )
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_query.order_by.return_value.limit.return_value.all.return_value = [mock_log]
        mock_db.query.return_value = mock_query

        from backend.core.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db
        try:
            resp = client.get("/api/v1/trade/trades?limit=50")
        finally:
            app.dependency_overrides.clear()
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["ticker"] == "US.AAPL"
        assert data[0]["action"] == "BUY"
