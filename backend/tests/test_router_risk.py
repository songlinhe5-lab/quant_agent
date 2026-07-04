"""routers/risk.py 单元测试

覆盖: dashboard / positions-breakdown
"""

import os
import sys
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app


def _unwrap(resp):
    body = resp.json()
    return body.get("data", body)


class TestRiskDashboard:
    def test_dashboard_success(self):
        """正常路径：获取风控面板数据"""
        mock_result = {
            "status": "success",
            "kpi": {"nav": 1000000, "pnl": 50000},
            "accounts": {},
        }
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/dashboard?days=7")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    def test_dashboard_error_response(self):
        """风控引擎返回错误时抛 500"""
        mock_result = {"status": "error", "message": "数据源不可用"}
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/dashboard")
        assert resp.status_code == 500

    def test_dashboard_default_days(self):
        """默认 days=1"""
        mock_result = {"status": "success", "kpi": {}}
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/dashboard")
        assert resp.status_code == 200
        # 验证调用时 days=1
        mock_engine.get_portfolio_risk.assert_called_once_with(days=1)


class TestPositionsBreakdown:
    def test_breakdown_success(self):
        """正常路径：获取持仓明细"""
        mock_result = {
            "status": "success",
            "ts": "2026-01-01T00:00:00Z",
            "accounts": {
                "HK": {
                    "positions": [
                        {"symbol": "00700.HK", "qty": 100, "market_value": 40000},
                        {"symbol": "09988.HK", "qty": 200, "market_value": 20000},
                    ]
                },
                "US": {
                    "positions": [
                        {"symbol": "AAPL", "qty": 50, "market_value": 10000},
                    ]
                },
            },
        }
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/positions-breakdown")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert len(data["positions"]) == 3

    def test_breakdown_empty(self):
        """空持仓路径"""
        mock_result = {
            "status": "success",
            "ts": "2026-01-01T00:00:00Z",
            "accounts": {},
        }
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/positions-breakdown")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["positions"] == []

    def test_breakdown_error_response(self):
        """风控引擎错误时返回 500"""
        mock_result = {"status": "error", "message": "Redis 不可用"}
        with patch("backend.routers.risk.risk_engine") as mock_engine:
            mock_engine.get_portfolio_risk = AsyncMock(return_value=mock_result)
            client = TestClient(app)
            resp = client.get("/api/v1/risk/positions-breakdown")
        assert resp.status_code == 500
