"""
OMS 路由测试
覆盖: backend/routers/oms.py
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from fastapi.testclient import TestClient

from backend.main import app
from backend.services.algo_engine import AlgoOrder


@pytest.fixture
def client():
    return TestClient(app)


def _unwrap(resp):
    """剥离 response_envelope_middleware 封装: {code, msg, data, ts}"""
    body = resp.json()
    if isinstance(body, dict) and "code" in body and "data" in body:
        return body["data"]
    return body


# ==========================================
# GET /oms/state
# ==========================================
class TestOmsState:
    @patch("backend.routers.oms.algo_engine")
    @patch("backend.routers.oms.bot_runtime")
    @patch("backend.routers.oms.oms_service")
    @patch("backend.routers.oms.redis_client")
    def test_get_state(self, mock_redis, mock_oms, mock_bot, mock_algo, client):
        """获取 OMS 初始状态"""
        mock_oms.get_active_orders = AsyncMock(return_value=[])
        mock_oms.get_historical_trades = AsyncMock(return_value=[])
        mock_bot.get_all_bots = AsyncMock(return_value=[])
        mock_algo.get_all_algo_orders = AsyncMock(return_value=[])
        mock_redis.get = AsyncMock(return_value="SANDBOX")
        resp = client.get("/api/v1/oms/state")
        assert resp.status_code == 200
        data = _unwrap(resp)
        # 可能被双层封装: {status, data: {bots, ...}}
        inner = data.get("data", data)
        assert "bots" in inner
        assert "trading_mode" in inner


# ==========================================
# POST /oms/kill_switch
# ==========================================
class TestKillSwitch:
    @patch("backend.routers.oms.log_audit")
    @patch("backend.routers.oms.redis_client")
    def test_kill_switch(self, mock_redis, mock_audit, client):
        """全局熔断"""
        with patch("backend.app.oms_app.engage_kill_switch_flags", new_callable=AsyncMock):
            with patch("backend.app.oms_app.run_emergency_liquidation", new_callable=AsyncMock):
                resp = client.post("/api/v1/oms/kill_switch", json={"timestamp": 1234567890})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"


# ==========================================
# POST /oms/orders/{order_id}/cancel
# ==========================================
class TestCancelOrder:
    @patch("backend.routers.oms.log_audit")
    @patch("backend.routers.oms.oms_service")
    @patch("backend.routers.oms.redis_client")
    def test_cancel_order_success(self, mock_redis, mock_oms, mock_audit, client):
        """撤单成功"""
        mock_redis.set = AsyncMock(return_value=True)  # NX 锁成功
        mock_redis.publish = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_oms.update_order_status = AsyncMock()
        resp = client.post(
            "/api/v1/oms/orders/order_123/cancel",
            json={"idempotency_key": "key_1"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.oms.redis_client")
    def test_cancel_order_duplicate(self, mock_redis, client):
        """重复撤单 (幂等性)"""
        mock_redis.set = AsyncMock(return_value=None)  # NX 锁失败
        resp = client.post(
            "/api/v1/oms/orders/order_123/cancel",
            json={"idempotency_key": "key_1"},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert "already" in data.get("message", "").lower()


# ==========================================
# GET /oms/positions
# ==========================================
class TestPositions:
    @patch("backend.routers.oms.oms_service")
    def test_get_positions(self, mock_oms, client):
        """获取持仓"""
        mock_oms.get_cached_positions = AsyncMock(return_value=[{"symbol": "US.AAPL", "qty": 100}])
        resp = client.get("/api/v1/oms/positions?market=US")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["market"] == "US"


# ==========================================
# Bot 控制端点
# ==========================================
class TestBotControl:
    @patch("backend.routers.oms.bot_runtime")
    def test_pause_bot_success(self, mock_bot, client):
        """暂停 Bot 成功"""
        mock_bot.pause_bot = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/bots/bot_1/pause")
        assert resp.status_code == 200

    @patch("backend.routers.oms.bot_runtime")
    def test_pause_bot_fail(self, mock_bot, client):
        """暂停 Bot 失败"""
        mock_bot.pause_bot = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/bots/bot_1/pause")
        assert resp.status_code == 400

    @patch("backend.routers.oms.bot_runtime")
    def test_resume_bot_success(self, mock_bot, client):
        """恢复 Bot 成功"""
        mock_bot.resume_bot = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/bots/bot_1/resume")
        assert resp.status_code == 200

    @patch("backend.routers.oms.bot_runtime")
    def test_resume_bot_fail(self, mock_bot, client):
        """恢复 Bot 失败"""
        mock_bot.resume_bot = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/bots/bot_1/resume")
        assert resp.status_code == 400

    @patch("backend.routers.oms.bot_runtime")
    def test_stop_bot_success(self, mock_bot, client):
        """终止 Bot 成功"""
        mock_bot.stop_bot = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/bots/bot_1/stop")
        assert resp.status_code == 200

    @patch("backend.routers.oms.bot_runtime")
    def test_stop_bot_fail(self, mock_bot, client):
        """终止 Bot 失败"""
        mock_bot.stop_bot = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/bots/bot_1/stop")
        assert resp.status_code == 400


# ==========================================
# 算法拆单端点
# ==========================================
class TestAlgoEndpoints:
    @patch("backend.routers.oms.algo_engine")
    def test_start_algo(self, mock_algo, client):
        """启动算法拆单"""
        mock_order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        mock_algo.start_algo = AsyncMock(return_value=mock_order)
        with patch("backend.routers.oms.log_audit"):
            with patch("backend.routers.oms.SessionLocal", create=True) as mock_sl:
                mock_db = MagicMock()
                mock_sl.return_value = mock_db
                resp = client.post(
                    "/api/v1/oms/algo/start",
                    json={
                        "algo_type": "TWAP",
                        "symbol": "US.AAPL",
                        "side": "BUY",
                        "target_qty": 1000,
                        "duration_minutes": 60,
                    },
                )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.oms.algo_engine")
    def test_pause_algo_success(self, mock_algo, client):
        """暂停算法"""
        mock_algo.pause_algo = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/algo/algo_1/pause")
        assert resp.status_code == 200

    @patch("backend.routers.oms.algo_engine")
    def test_pause_algo_fail(self, mock_algo, client):
        """暂停算法失败"""
        mock_algo.pause_algo = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/algo/algo_1/pause")
        assert resp.status_code == 400

    @patch("backend.routers.oms.algo_engine")
    def test_resume_algo_success(self, mock_algo, client):
        """恢复算法"""
        mock_algo.resume_algo = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/algo/algo_1/resume")
        assert resp.status_code == 200

    @patch("backend.routers.oms.algo_engine")
    def test_resume_algo_fail(self, mock_algo, client):
        """恢复算法失败"""
        mock_algo.resume_algo = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/algo/algo_1/resume")
        assert resp.status_code == 400

    @patch("backend.routers.oms.algo_engine")
    def test_cancel_algo_success(self, mock_algo, client):
        """取消算法"""
        mock_algo.cancel_algo = AsyncMock(return_value=True)
        resp = client.post("/api/v1/oms/algo/algo_1/cancel")
        assert resp.status_code == 200

    @patch("backend.routers.oms.algo_engine")
    def test_cancel_algo_fail(self, mock_algo, client):
        """取消算法失败"""
        mock_algo.cancel_algo = AsyncMock(return_value=False)
        resp = client.post("/api/v1/oms/algo/algo_1/cancel")
        assert resp.status_code == 400


# ==========================================
# 算法分析端点
# ==========================================
class TestAlgoAnalytics:
    @patch("backend.routers.oms.algo_analytics")
    @patch("backend.routers.oms.algo_engine")
    def test_analytics_success(self, mock_algo, mock_analytics, client):
        """算法分析报告"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 500
        order.total_cost = 75000.0
        mock_algo._orders = {"algo_1": order}
        mock_analytics.execution_report.return_value = {"slippage_bps": 2.5}
        resp = client.post(
            "/api/v1/oms/algo/analytics/algo_1",
            json={"benchmark_price": 150.0, "market_volume": 1000000, "market_vwap": 149.5, "fills": []},
        )
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"

    @patch("backend.routers.oms.algo_engine")
    def test_analytics_not_found(self, mock_algo, client):
        """算法不存在"""
        mock_algo._orders = {}
        resp = client.post(
            "/api/v1/oms/algo/analytics/nonexist",
            json={"benchmark_price": 150.0},
        )
        assert resp.status_code == 404


# ==========================================
# 交易模式端点
# ==========================================
class TestTradingMode:
    @patch("backend.routers.oms.redis_client")
    def test_get_mode(self, mock_redis, client):
        """获取交易模式"""
        mock_redis.get = AsyncMock(return_value="SANDBOX")
        resp = client.get("/api/v1/oms/mode")
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"]["mode"] == "SANDBOX"

    @patch("backend.routers.oms.log_audit")
    @patch("backend.routers.oms.redis_client")
    def test_switch_mode_success(self, mock_redis, mock_audit, client):
        """切换交易模式"""
        mock_redis.get = AsyncMock(return_value="SANDBOX")
        mock_redis.set = AsyncMock()
        mock_redis.publish = AsyncMock()
        resp = client.post("/api/v1/oms/mode/switch", json={"mode": "PAPER"})
        assert resp.status_code == 200
        data = _unwrap(resp)
        assert data["status"] == "success"
        assert data["data"]["mode"] == "PAPER"

    def test_switch_mode_invalid(self, client):
        """无效模式"""
        resp = client.post("/api/v1/oms/mode/switch", json={"mode": "INVALID"})
        assert resp.status_code == 400


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
