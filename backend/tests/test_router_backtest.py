"""
回测引擎路由单元测试
覆盖: backend/routers/backtest.py
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


class TestBacktestRunRoutes:
    """回测执行接口路由测试"""

    def test_run_backtest_invalid_payload(self):
        """参数校验：缺少 ticker 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/backtest/run", json={})
        assert resp.status_code == 422

    @patch("backend.routers.backtest.yf_service")
    @patch("backend.routers.backtest.futu_service")
    def test_run_backtest_data_load_fail(self, mock_futu, mock_yf):
        """异常路径：所有数据源均失败返回 400"""
        mock_futu.get_history = AsyncMock(return_value={"status": "error", "message": "连接失败"})
        mock_yf.fetch_yf_data = AsyncMock(return_value=(False, None, "YFinance 限流"))
        client = TestClient(app)
        resp = client.post(
            "/api/v1/backtest/run",
            json={"ticker": "US.AAPL", "period": "1mo", "data_source": "auto"},
        )
        assert resp.status_code == 400
        # HTTPException 被处理器包装成 {code, msg, data, ts} 格式
        body = resp.json()
        assert "回测数据加载失败" in body["msg"]

    @patch("backend.routers.backtest.DivergenceResonanceStrategy")
    @patch("backend.routers.backtest.futu_service")
    def test_run_backtest_builtin_strategy_success(self, mock_futu, mock_strategy_cls):
        """正常路径：内置底背离共振策略回测成功"""
        mock_futu.get_history = AsyncMock(
            return_value={
                "status": "success",
                "data": [
                    {
                        "time": "2026-01-01",
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "volume": 10000,
                    }
                ],
            }
        )
        mock_engine = MagicMock()
        mock_engine.run = MagicMock(return_value={"total_return": 0.05})
        mock_strategy_cls.return_value = mock_engine
        client = TestClient(app)
        resp = client.post(
            "/api/v1/backtest/run",
            json={"ticker": "US.AAPL", "period": "1mo", "data_source": "futu"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "data" in data

    @patch("backend.routers.backtest.run_dynamic_sandbox_backtest")
    @patch("backend.routers.backtest.futu_service")
    def test_run_backtest_dynamic_strategy_success(self, mock_futu, mock_run):
        """正常路径：动态策略代码回测成功"""
        mock_futu.get_history = AsyncMock(
            return_value={
                "status": "success",
                "data": [
                    {
                        "time": "2026-01-01",
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "volume": 10000,
                    }
                ],
            }
        )
        mock_run.return_value = {"total_return": 0.08}
        client = TestClient(app)
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ticker": "US.AAPL",
                "period": "1mo",
                "data_source": "futu",
                "source_code": "class S: pass",
                "class_name": "S",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.backtest.run_dynamic_sandbox_backtest")
    @patch("backend.routers.backtest.futu_service")
    def test_run_backtest_dynamic_strategy_exception(self, mock_futu, mock_run):
        """异常路径：动态策略执行抛异常时返回 error"""
        mock_futu.get_history = AsyncMock(
            return_value={
                "status": "success",
                "data": [
                    {
                        "time": "2026-01-01",
                        "open": 100.0,
                        "high": 102.0,
                        "low": 99.0,
                        "close": 101.0,
                        "volume": 10000,
                    }
                ],
            }
        )
        mock_run.side_effect = ValueError("参数无效")
        client = TestClient(app)
        resp = client.post(
            "/api/v1/backtest/run",
            json={
                "ticker": "US.AAPL",
                "period": "1mo",
                "data_source": "futu",
                "source_code": "class S: pass",
                "class_name": "S",
                "params": {},
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "error"
        assert "参数无效" in data["message"]
