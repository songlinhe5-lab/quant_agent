"""
Algo Engine 单元测试
覆盖: backend/services/algo_engine.py
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── AlgoOrder 单元测试 ────────────────────────────────────────────────────────
class TestAlgoOrder:
    """AlgoOrder 数据结构测试"""

    def test_algo_order_init(self):
        """AlgoOrder 初始化"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder(
            algo_id="algo_twap_001",
            algo_type="TWAP",
            symbol="00700.HK",
            side="BUY",
            target_qty=1000,
            duration_minutes=30,
        )

        assert order.algo_id == "algo_twap_001"
        assert order.algo_type == "TWAP"
        assert order.symbol == "00700.HK"
        assert order.side == "BUY"
        assert order.target_qty == 1000
        assert order.filled_qty == 0
        assert order.status == "RUNNING"
        assert order.lot_size == 1

    def test_algo_order_avg_price_zero(self):
        """无成交时均价为 0"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder("id1", "TWAP", "00700.HK", "BUY", 100)
        assert order.avg_price == "0.00"

    def test_algo_order_avg_price_with_fills(self):
        """有成交时计算均价"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder("id1", "TWAP", "00700.HK", "BUY", 100)
        order.filled_qty = 100
        order.total_cost = 40000.0
        assert order.avg_price == "400.00"

    def test_algo_order_progress(self):
        """进度计算"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder("id1", "TWAP", "00700.HK", "BUY", 1000)
        order.filled_qty = 500
        assert order.progress == 50

    def test_algo_order_progress_zero_target(self):
        """目标为 0 时进度 100%"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder("id1", "TWAP", "00700.HK", "BUY", 0)
        assert order.progress == 100

    def test_algo_order_to_api_dict(self):
        """转 API 格式"""
        from backend.services.algo_engine import AlgoOrder

        order = AlgoOrder("id1", "TWAP", "00700.HK", "BUY", 1000)
        order.filled_qty = 200
        order.total_cost = 80000.0
        order.status = "RUNNING"
        order.message = "执行中"

        result = order.to_api_dict()

        assert result["id"] == "id1"
        assert result["algo_type"] == "TWAP"
        assert result["symbol"] == "00700.HK"
        assert result["target_qty"] == 1000
        assert result["filled_qty"] == 200
        assert result["avg_price"] == "400.00"
        assert result["progress"] == 20
        assert result["status"] == "RUNNING"


# ─── AlgoEngine 单元测试 ───────────────────────────────────────────────────────
class TestAlgoEngine:
    """AlgoEngine 核心逻辑测试"""

    @patch("backend.services.algo_engine.redis_client")
    def test_pause_algo(self, mock_redis):
        """暂停算法"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "RUNNING"
        engine._orders["algo_001"] = order

        result = asyncio.run(engine.pause_algo("algo_001"))

        assert result is True
        assert order.status == "PAUSED"
        assert order._pause_event.is_set() is False

    @patch("backend.services.algo_engine.redis_client")
    def test_pause_algo_not_found(self, mock_redis):
        """暂停不存在的算法返回 False"""
        from backend.services.algo_engine import AlgoEngine

        engine = AlgoEngine()

        result = asyncio.run(engine.pause_algo("nonexistent"))
        assert result is False

    @patch("backend.services.algo_engine.redis_client")
    def test_resume_algo(self, mock_redis):
        """恢复暂停的算法"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "PAUSED"
        order._pause_event.clear()
        engine._orders["algo_001"] = order

        result = asyncio.run(engine.resume_algo("algo_001"))

        assert result is True
        assert order.status == "RUNNING"
        assert order._pause_event.is_set() is True

    @patch("backend.services.algo_engine.redis_client")
    def test_resume_algo_not_paused(self, mock_redis):
        """恢复非 PAUSED 状态的算法返回 False"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "RUNNING"
        engine._orders["algo_001"] = order

        result = asyncio.run(engine.resume_algo("algo_001"))
        assert result is False

    @patch("backend.services.algo_engine.redis_client")
    async def test_cancel_algo(self, mock_redis):
        """取消算法"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "RUNNING"
        order.task = asyncio.create_task(asyncio.sleep(10))
        engine._orders["algo_001"] = order

        result = await engine.cancel_algo("algo_001")

        assert result is True
        assert order.status == "CANCELLED"
        assert order._stop_requested is True

    @patch("backend.services.algo_engine.redis_client")
    async def test_cancel_all(self, mock_redis):
        """Kill Switch: 取消所有运行中算法"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()

        engine = AlgoEngine()
        order1 = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order1.status = "RUNNING"
        order1.task = asyncio.create_task(asyncio.sleep(10))
        order2 = AlgoOrder("algo_002", "VWAP", "00700.HK", "SELL", 500)
        order2.status = "PAUSED"
        order2.task = asyncio.create_task(asyncio.sleep(10))
        order3 = AlgoOrder("algo_003", "ICEBERG", "00700.HK", "BUY", 200)
        order3.status = "COMPLETED"
        engine._orders = {"algo_001": order1, "algo_002": order2, "algo_003": order3}

        result = await engine.cancel_all()

        assert result == 2

    @patch("backend.services.algo_engine.redis_client")
    def test_get_all_algo_orders(self, mock_redis):
        """获取所有算法订单"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        engine = AlgoEngine()
        order1 = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order2 = AlgoOrder("algo_002", "VWAP", "09988.HK", "SELL", 500)
        engine._orders = {"algo_001": order1, "algo_002": order2}

        result = asyncio.run(engine.get_all_algo_orders())

        assert len(result) == 2
        assert result[0]["id"] == "algo_001"
        assert result[1]["id"] == "algo_002"

    @patch("backend.services.algo_engine.redis_client")
    def test_save_algo_state_completed(self, mock_redis):
        """完成状态时从活动表移除"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hdel = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "COMPLETED"

        asyncio.run(engine._save_algo_state(order))

        mock_redis.hdel.assert_called_once()

    @patch("backend.services.algo_engine.redis_client")
    def test_archive_algo(self, mock_redis):
        """归档已完成算法"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "COMPLETED"

        asyncio.run(engine._archive_algo(order))

        mock_redis.lpush.assert_called_once()
        mock_redis.ltrim.assert_called_once()
        mock_redis.expire.assert_called_once()

    @patch("backend.services.algo_engine.redis_client")
    def test_archive_algo_running_skip(self, mock_redis):
        """运行中的算法不归档"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.lpush = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "RUNNING"

        asyncio.run(engine._archive_algo(order))

        mock_redis.lpush.assert_not_called()

    @patch("backend.services.algo_engine.redis_client")
    def test_restore_from_redis_empty(self, mock_redis):
        """Redis 无活动订单时恢复 0"""
        from backend.services.algo_engine import AlgoEngine

        mock_redis.hgetall = AsyncMock(return_value={})

        engine = AlgoEngine()

        result = asyncio.run(engine.restore_from_redis())
        assert result == 0

    @patch("backend.services.algo_engine.redis_client")
    async def test_shutdown(self, mock_redis):
        """优雅关停"""
        from backend.services.algo_engine import AlgoEngine, AlgoOrder

        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.publish = AsyncMock()

        engine = AlgoEngine()
        order = AlgoOrder("algo_001", "TWAP", "00700.HK", "BUY", 1000)
        order.status = "RUNNING"
        order.task = asyncio.create_task(asyncio.sleep(10))
        engine._orders = {"algo_001": order}

        await engine.shutdown()

        assert order.status == "CANCELLED"


# ─── lot_size 工具函数测试 ─────────────────────────────────────────────────────
class TestGetLotSize:
    """lot_size 获取逻辑测试"""

    def test_us_stock_returns_1(self):
        """美股默认返回 1"""
        from backend.services.algo_engine import _get_lot_size

        result = asyncio.run(_get_lot_size("AAPL"))
        assert result == 1

    @patch("backend.services.algo_engine.futu_service", create=True)
    def test_hk_stock_fallback_to_hardcoded(self, mock_futu_module):
        """港股 snapshot 失败时降级到硬编码"""
        from backend.services.algo_engine import _get_lot_size

        with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock()}):
            result = asyncio.run(_get_lot_size("00700.HK"))
            assert result == 100

    def test_hk_stock_unknown_defaults_100(self):
        """未知港股默认 100"""
        from backend.services.algo_engine import _get_lot_size

        with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock()}):
            result = asyncio.run(_get_lot_size("99999.HK"))
            assert result == 100

    async def test_hk_stock_from_snapshot(self):
        """港股从 snapshot 成功获取 lot_size"""
        from backend.services.algo_engine import _get_lot_size

        mock_futu = MagicMock()
        mock_futu.get_market_snapshots = AsyncMock(return_value={"status": "success", "data": [{"lot_size": 500}]})

        with patch.dict("sys.modules", {"backend.services.futu_service": mock_futu}):
            result = await _get_lot_size("00005.HK")
            assert result == 500


class TestAlgoEngineSimulateFill:
    """模拟成交逻辑测试"""

    @patch("backend.services.algo_engine.redis_client")
    async def test_simulate_fill_sandbox_mode(self, mock_redis):
        """沙箱模式模拟成交"""
        from backend.services.algo_engine import AlgoEngine

        mock_redis.get = AsyncMock(return_value="SANDBOX")

        mock_futu_service = AsyncMock(return_value={"status": "success", "last_price": 400.0})

        mock_module = MagicMock()
        mock_module.futu_service.get_quote = mock_futu_service

        engine = AlgoEngine()
        with patch.dict("sys.modules", {"backend.services.futu_service": mock_module}):
            price = await engine._simulate_fill("00700.HK", 100, "BUY")
            # 价格应该在 400 附近有微小滑点
            assert 400.0 < price < 400.5

    @patch("backend.services.algo_engine.redis_client")
    async def test_simulate_fill_fallback_price(self, mock_redis):
        """行情获取失败时使用默认价格"""
        from backend.services.algo_engine import AlgoEngine

        mock_redis.get = AsyncMock(return_value="SANDBOX")

        mock_module = MagicMock()
        mock_module.futu_service.get_quote = AsyncMock(side_effect=Exception("Connection failed"))

        engine = AlgoEngine()
        with patch.dict("sys.modules", {"backend.services.futu_service": mock_module}):
            price = await engine._simulate_fill("00700.HK", 100, "BUY")
            assert price == 100.0
