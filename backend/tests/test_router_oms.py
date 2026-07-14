"""
OMS 订单管理与实盘 Bot 路由单元测试
覆盖: backend/routers/oms.py
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
    """剥离统一响应封装，返回路由原始 dict"""
    body = resp.json()
    return body.get("data", body)


class TestOmsStateRoutes:
    """OMS 初始状态查询路由测试"""

    @patch("backend.routers.oms.redis_client")
    @patch("backend.routers.oms.bot_runtime")
    @patch("backend.routers.oms.algo_engine")
    @patch("backend.routers.oms.oms_service")
    def test_get_oms_state_success(self, mock_oms, mock_algo, mock_bot, mock_redis):
        """正常路径：获取 OMS 初始状态"""
        mock_oms.get_active_orders = AsyncMock(return_value=[])
        mock_oms.get_historical_trades = AsyncMock(return_value=[])
        mock_bot.get_all_bots = AsyncMock(return_value=[])
        mock_algo.get_all_algo_orders = AsyncMock(return_value=[])
        mock_redis.get = AsyncMock(return_value=None)
        client = TestClient(app)
        resp = client.get("/api/v1/oms/state")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "bots" in data["data"]
        assert "active_orders" in data["data"]
        assert "historical_trades" in data["data"]
        assert "algo_executions" in data["data"]


class TestOmsKillSwitchRoutes:
    """全局熔断 Kill Switch 路由测试"""

    @patch("backend.routers.oms.redis_client")
    def test_trigger_kill_switch_success(self, mock_redis):
        """正常路径：触发熔断信号成功"""
        mock_redis.publish = AsyncMock()
        mock_redis.set = AsyncMock()
        client = TestClient(app)
        resp = client.post("/api/v1/oms/kill_switch", json={"timestamp": 1719500000})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "Kill switch" in data["message"]

    def test_trigger_kill_switch_invalid_payload(self):
        """参数校验：缺少 timestamp 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/oms/kill_switch", json={})
        assert resp.status_code == 422


class TestOmsCancelOrderRoutes:
    """撤单接口路由测试"""

    @patch("backend.routers.oms.redis_client")
    def test_cancel_order_first_request(self, mock_redis):
        """正常路径：首次撤单请求成功"""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.publish = AsyncMock()
        mock_redis.delete = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/orders/ord_1001/cancel",
            json={"idempotency_key": "idem-001"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.oms.redis_client")
    def test_cancel_order_idempotent_retry(self, mock_redis):
        """幂等路径：重复撤单返回 already in progress"""
        mock_redis.set = AsyncMock(return_value=None)  # NX 失败，已存在
        mock_redis.publish = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/orders/ord_1001/cancel",
            json={"idempotency_key": "idem-dup"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "already in progress" in data["message"]


class TestOmsModifyOrderRoutes:
    """改单接口路由测试"""

    @patch("backend.routers.oms.redis_client")
    def test_modify_order_success(self, mock_redis):
        """正常路径：改单指令下发成功"""
        mock_redis.publish = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/orders/ord_1001/modify",
            json={"price": 435.50},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert "改单" in data["message"]

    def test_modify_order_invalid_payload(self):
        """参数校验：缺少 price 返回 422"""
        client = TestClient(app)
        resp = client.post("/api/v1/oms/orders/ord_1001/modify", json={})
        assert resp.status_code == 422


class TestOmsAlgoStartRoutes:
    """算法拆单启动接口路由测试"""

    @patch("backend.routers.oms.redis_client")
    def test_start_algo_order_success(self, mock_redis):
        """正常路径：启动 TWAP 算法任务"""
        mock_redis.publish = AsyncMock()
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/algo/start",
            json={
                "algo_type": "TWAP",
                "symbol": "US.QQQ",
                "side": "BUY",
                "target_qty": 1000,
                "duration_minutes": 30,
            },
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"]["algo_type"] == "TWAP"
        assert data["data"]["status"] == "RUNNING"

    def test_start_algo_order_invalid_payload(self):
        """参数校验：缺少必填字段返回 422"""
        client = TestClient(app)
        resp = client.post(
            "/api/v1/oms/algo/start",
            json={"algo_type": "TWAP"},
        )
        assert resp.status_code == 422


class TestOmsEmergencyLiquidation:
    """物理级熔断清仓逻辑测试"""

    @patch("backend.app.oms_app.redis_client")
    @patch("backend.app.oms_app.bot_runtime")
    @patch("backend.app.oms_app.algo_engine")
    @patch("backend.app.oms_app.oms_service")
    @patch("backend.app.oms_app.broker")
    async def test_execute_emergency_liquidation_no_trade_ctx(
        self, mock_broker, mock_oms, mock_algo, mock_bot, mock_redis
    ):
        """降级路径：无 trade_ctx 时走沙箱 Mock 强平"""
        from unittest.mock import MagicMock

        mock_db = MagicMock()
        mock_broker.execute_emergency_liquidation = AsyncMock(return_value={"ok": False, "reason": "no_trade_ctx"})
        mock_bot.stop_all_bots = AsyncMock()
        mock_algo.cancel_all = AsyncMock()
        mock_oms.mark_all_orders_cancelled = AsyncMock()
        mock_redis.publish = AsyncMock()
        from backend.app.oms_app import run_emergency_liquidation

        await run_emergency_liquidation(mock_db)
        mock_bot.stop_all_bots.assert_awaited_once()
        mock_algo.cancel_all.assert_awaited_once()
        mock_oms.mark_all_orders_cancelled.assert_awaited_once()
