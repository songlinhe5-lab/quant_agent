"""
TRADE-02 · 算法拆单增强测试

5 tests: 市场冲击模型 / POV 算法 / IS 算法 / VWAP ADV 曲线 / 执行分析
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.algo_analytics import (
    AlgoAnalytics,
    algo_analytics,
)
from backend.services.algo_engine import (
    AlgoEngine,
    AlgoOrder,
    MarketImpactModel,
    algo_engine,
)

# ===== MarketImpactModel =====


class TestMarketImpactModel:
    """市场冲击模型测试"""

    def test_estimate_slippage_basic(self):
        """测试滑点估计基本正确性"""
        # 10% ADV 参与率, 20% 波动率
        slippage = MarketImpactModel.estimate_slippage(qty=10000, adv=100000, volatility=0.20)
        # slippage = 0.5 * 0.20 * sqrt(0.1) * 10000 = 0.5 * 0.20 * 0.316 * 10000 = 316 bps
        assert 200 < slippage < 400, f"滑点估计异常: {slippage}"

    def test_estimate_slippage_zero_input(self):
        """测试零输入"""
        assert MarketImpactModel.estimate_slippage(0, 100000, 0.20) == 0
        assert MarketImpactModel.estimate_slippage(10000, 0, 0.20) == 0

    def test_estimate_slippage_monotonic(self):
        """测试滑点随参与率单调递增"""
        slippages = []
        for qty in [1000, 5000, 10000, 20000, 50000]:
            s = MarketImpactModel.estimate_slippage(qty, 100000, 0.20)
            slippages.append(s)

        # 单调递增
        for i in range(1, len(slippages)):
            assert slippages[i] >= slippages[i - 1], f"滑点应单调递增: {slippages}"

    def test_optimal_schedule_total(self):
        """测试最优计划总量守恒"""
        adv_curve = [10000, 8000, 6000, 5000, 4000, 3000]
        schedule = MarketImpactModel.optimal_schedule(
            target_qty=10000,
            adv_curve=adv_curve,
            volatility=0.20,
            risk_aversion=1.0,
        )

        assert sum(schedule) == 10000, f"计划总量不守恒: {sum(schedule)} vs 10000"
        assert len(schedule) == len(adv_curve)

    def test_optimal_schedule_front_loaded(self):
        """测试高风险厌恶导致前倾执行"""
        adv_curve = [10000] * 10  # 均匀 ADV
        schedule = MarketImpactModel.optimal_schedule(
            target_qty=10000,
            adv_curve=adv_curve,
            volatility=0.20,
            risk_aversion=3.0,  # 高风险厌恶
        )

        # 前期执行量应大于后期
        first_half = sum(schedule[:5])
        second_half = sum(schedule[5:])
        assert first_half > second_half, f"高风险厌恶应前倾: {first_half} vs {second_half}"

    def test_optimal_schedule_empty(self):
        """测试空输入"""
        assert MarketImpactModel.optimal_schedule(0, [1000], 0.20) == []
        assert MarketImpactModel.optimal_schedule(1000, [], 0.20) == []


# ===== AlgoAnalytics =====


class TestAlgoAnalytics:
    """算法执行分析测试"""

    def test_slippage_buy_favorable(self):
        """测试买入有利执行的滑点"""
        # 买入均价 99, 基准 100 -> 有利 100 bps
        slippage = AlgoAnalytics.compute_slippage(99, 100, "BUY")
        assert slippage == 100.0, f"买入有利滑点异常: {slippage}"

    def test_slippage_sell_unfavorable(self):
        """测试卖出不利执行的滑点"""
        # 卖出均价 98, 基准 100 -> 不利 -200 bps
        slippage = AlgoAnalytics.compute_slippage(98, 100, "SELL")
        assert slippage == -200.0, f"卖出不利滑点异常: {slippage}"

    def test_vwap_deviation(self):
        """测试 VWAP 偏离度"""
        # 实际 VWAP 99.5, 市场 VWAP 100 -> 偏离 50 bps (有利)
        dev = AlgoAnalytics.vwap_deviation(99.5, 100)
        assert dev == 50.0

    def test_participation_rate(self):
        """测试参与率"""
        rate = AlgoAnalytics.participation_rate(5000, 100000)
        assert rate == 0.05

    def test_implementation_shortfall(self):
        """测试 Implementation Shortfall"""
        # 买入: 实际成本 101000, 纸面成本 100000 -> IS = 100 bps
        is_bps = AlgoAnalytics.implementation_shortfall(101000, 100000, "BUY")
        assert is_bps == 100.0

    def test_execution_report(self):
        """测试完整执行报告"""
        report = AlgoAnalytics.execution_report(
            algo_id="algo_twap_123",
            algo_type="TWAP",
            symbol="US.AAPL",
            side="BUY",
            target_qty=1000,
            filled_qty=1000,
            total_cost=150000,  # 均价 150
            benchmark_price=149,
            market_volume=50000,
            market_vwap=149.5,
            fills=[
                {"timestamp": 0, "qty": 200, "price": 149.5},
                {"timestamp": 300, "qty": 200, "price": 150.0},
                {"timestamp": 600, "qty": 200, "price": 150.2},
                {"timestamp": 900, "qty": 200, "price": 150.3},
                {"timestamp": 1200, "qty": 200, "price": 150.0},
            ],
            duration_minutes=60,
        )

        assert report["algo_id"] == "algo_twap_123"
        assert report["summary"]["completion_pct"] == 100.0
        assert "quality_metrics" in report
        assert "time_distribution" in report
        assert report["assessment"] in ["EXCELLENT", "GOOD", "ACCEPTABLE", "POOR"]

    def test_time_distribution(self):
        """测试时间分布聚合"""
        fills = [
            {"timestamp": 0, "qty": 100, "price": 100},
            {"timestamp": 60, "qty": 100, "price": 101},
            {"timestamp": 300, "qty": 200, "price": 102},
            {"timestamp": 600, "qty": 100, "price": 103},
        ]

        dist = AlgoAnalytics.time_distribution(fills, 60)

        assert len(dist) > 0
        total_qty = sum(d["qty"] for d in dist)
        assert total_qty == 500


# ===== AlgoEngine POV/IS =====


class TestAlgoEngineNewAlgorithms:
    """新增算法 (POV/IS) 测试"""

    def test_pov_algorithm_type(self):
        """测试 POV 算法类型支持"""
        AlgoEngine()
        # 验证 POV 被识别
        order = AlgoOrder(
            algo_id="test_pov",
            algo_type="POV",
            symbol="US.AAPL",
            side="BUY",
            target_qty=1000,
        )
        assert order.algo_type == "POV"

    def test_is_algorithm_type(self):
        """测试 IS 算法类型支持"""
        order = AlgoOrder(
            algo_id="test_is",
            algo_type="IS",
            symbol="US.AAPL",
            side="BUY",
            target_qty=1000,
        )
        assert order.algo_type == "IS"

    def test_global_singleton(self):
        """测试全局单例"""
        assert algo_engine is not None
        assert isinstance(algo_engine, AlgoEngine)

    def test_algo_analytics_singleton(self):
        """测试分析单例"""
        assert algo_analytics is not None
        assert isinstance(algo_analytics, AlgoAnalytics)


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
