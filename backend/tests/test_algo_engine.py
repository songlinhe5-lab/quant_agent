"""
算法拆单引擎测试
覆盖: backend/services/algo_engine.py
"""

import asyncio
import json
import math
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.algo_analytics import (
    AlgoAnalytics,
    algo_analytics,
)
from backend.services.algo_engine import (
    AlgoEngine,
    AlgoOrder,
    MarketImpactModel,
    _get_lot_size,
    algo_engine,
)


# ==========================================
# MarketImpactModel 测试
# ==========================================
class TestMarketImpactModel:
    def test_estimate_slippage_basic(self):
        """基本滑点估算"""
        slippage = MarketImpactModel.estimate_slippage(qty=1000, adv=100000, volatility=0.20)
        assert slippage > 0
        assert isinstance(slippage, float)

    def test_estimate_slippage_zero_adv(self):
        """ADV 为 0 返回 0"""
        assert MarketImpactModel.estimate_slippage(qty=1000, adv=0, volatility=0.20) == 0.0

    def test_estimate_slippage_zero_qty(self):
        """数量为 0 返回 0"""
        assert MarketImpactModel.estimate_slippage(qty=0, adv=100000, volatility=0.20) == 0.0

    def test_estimate_slippage_formula(self):
        """验证公式: eta * sigma * sqrt(qty/ADV) * 10000"""
        qty, adv, vol, eta = 10000, 1000000, 0.30, 0.5
        expected = eta * vol * math.sqrt(qty / adv) * 10000
        result = MarketImpactModel.estimate_slippage(qty, adv, vol, eta)
        assert abs(result - round(expected, 2)) < 0.01

    def test_optimal_schedule_basic(self):
        """IS 最优执行计划基本功能"""
        schedule = MarketImpactModel.optimal_schedule(
            target_qty=10000,
            adv_curve=[10000, 8000, 6000, 4000],
            volatility=0.20,
            risk_aversion=1.0,
        )
        assert len(schedule) == 4
        assert sum(schedule) == 10000
        # 前期应分配更多 (风险厌恶)
        assert schedule[0] >= schedule[-1]

    def test_optimal_schedule_empty_curve(self):
        """空 ADV 曲线返回空列表"""
        assert MarketImpactModel.optimal_schedule(1000, [], 0.20) == []

    def test_optimal_schedule_zero_qty(self):
        """目标数量为 0 返回空列表"""
        assert MarketImpactModel.optimal_schedule(0, [1000, 2000], 0.20) == []

    def test_optimal_schedule_zero_total_adv(self):
        """总 ADV 为 0 时均匀分配"""
        schedule = MarketImpactModel.optimal_schedule(100, [0, 0, 0, 0], 0.20)
        assert len(schedule) == 4
        assert sum(schedule) == 100

    def test_optimal_schedule_high_risk_aversion(self):
        """高风险厌恶 → 前期更激进"""
        schedule_high = MarketImpactModel.optimal_schedule(10000, [5000] * 10, 0.20, risk_aversion=5.0)
        schedule_low = MarketImpactModel.optimal_schedule(10000, [5000] * 10, 0.20, risk_aversion=0.1)
        # 高风险厌恶时第一笔占比更大
        assert schedule_high[0] > schedule_low[0]


# ==========================================
# AlgoOrder 测试
# ==========================================
class TestAlgoOrder:
    def test_order_creation(self):
        """创建算法订单"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        assert order.algo_id == "algo_1"
        assert order.algo_type == "TWAP"
        assert order.symbol == "US.AAPL"
        assert order.side == "BUY"
        assert order.target_qty == 1000
        assert order.filled_qty == 0
        assert order.status == "RUNNING"

    def test_avg_price_zero_fill(self):
        """无成交时均价为 0.00"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        assert order.avg_price == "0.00"

    def test_avg_price_with_fills(self):
        """有成交时正确计算均价"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 500
        order.total_cost = 75000.0
        assert order.avg_price == "150.00"

    def test_progress_zero(self):
        """初始进度为 0"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        assert order.progress == 0

    def test_progress_partial(self):
        """部分成交进度"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 300
        assert order.progress == 30

    def test_progress_full(self):
        """全部成交进度 100"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 1000
        assert order.progress == 100

    def test_progress_zero_target(self):
        """目标为 0 时进度 100"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 0)
        assert order.progress == 100

    def test_to_api_dict(self):
        """API 字典格式"""
        order = AlgoOrder("algo_1", "VWAP", "00700.HK", "SELL", 500)
        d = order.to_api_dict()
        assert d["id"] == "algo_1"
        assert d["algo_type"] == "VWAP"
        assert d["symbol"] == "00700.HK"
        assert d["target_qty"] == 500
        assert d["filled_qty"] == 0
        assert d["status"] == "RUNNING"
        assert "avg_price" in d
        assert "progress" in d


# ==========================================
# _get_lot_size 测试
# ==========================================
class TestGetLotSize:
    @pytest.mark.asyncio
    async def test_us_stock_returns_1(self):
        """美股 lot_size = 1"""
        lot = await _get_lot_size("US.AAPL")
        assert lot == 1

    @pytest.mark.asyncio
    async def test_hk_stock_snapshot(self):
        """港股从 snapshot 获取 lot_size"""
        with patch("backend.services.algo_engine.futu_service", create=True) as mock_futu:
            mock_futu.get_market_snapshots = AsyncMock(return_value={"status": "success", "data": [{"lot_size": 100}]})
            # 需要 patch import
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                lot = await _get_lot_size("00700.HK")
        # 如果 snapshot 失败会走硬编码映射
        assert lot in (100, 100)

    @pytest.mark.asyncio
    async def test_hk_stock_hardcoded_fallback(self):
        """港股硬编码兜底"""
        with patch("backend.services.algo_engine.futu_service", create=True) as mock_futu:
            mock_futu.get_market_snapshots = AsyncMock(side_effect=Exception("连接失败"))
            mock_futu.get_quote = AsyncMock(side_effect=Exception("连接失败"))
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                lot = await _get_lot_size("00700.HK")
        assert lot == 100  # 腾讯硬编码

    @pytest.mark.asyncio
    async def test_hk_unknown_stock_default(self):
        """未知港股默认 100"""
        with patch("backend.services.algo_engine.futu_service", create=True) as mock_futu:
            mock_futu.get_market_snapshots = AsyncMock(side_effect=Exception("err"))
            mock_futu.get_quote = AsyncMock(side_effect=Exception("err"))
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                lot = await _get_lot_size("09999.HK")
        # 09999.HK 在硬编码映射中 = 100
        assert lot == 100


# ==========================================
# AlgoEngine 测试
# ==========================================
class TestAlgoEngine:
    @pytest.fixture
    def engine(self):
        return AlgoEngine()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_start_algo(self, mock_redis, engine):
        """启动算法拆单"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # trading mode = SANDBOX
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()

        with patch.object(engine, "_run_algo_loop", new_callable=AsyncMock):
            with patch("backend.services.algo_engine._get_lot_size", new_callable=AsyncMock, return_value=1):
                order = await engine.start_algo("TWAP", "US.AAPL", "BUY", 1000, 60)
                assert order.algo_type == "TWAP"
                assert order.symbol == "US.AAPL"
                assert order.target_qty == 1000
                assert order.status == "RUNNING"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_pause_algo(self, mock_redis, engine):
        """暂停算法"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        engine._orders["algo_1"] = order
        result = await engine.pause_algo("algo_1")
        assert result is True
        assert order.status == "PAUSED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_pause_nonexistent(self, mock_redis, engine):
        """暂停不存在的算法"""
        result = await engine.pause_algo("nonexist")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_resume_algo(self, mock_redis, engine):
        """恢复算法"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.status = "PAUSED"
        order._pause_event.clear()
        engine._orders["algo_1"] = order
        result = await engine.resume_algo("algo_1")
        assert result is True
        assert order.status == "RUNNING"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_resume_not_paused(self, mock_redis, engine):
        """恢复非暂停状态的算法"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        engine._orders["algo_1"] = order
        result = await engine.resume_algo("algo_1")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_cancel_algo(self, mock_redis, engine):
        """取消算法"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        engine._orders["algo_1"] = order
        result = await engine.cancel_algo("algo_1")
        assert result is True
        assert order.status == "CANCELLED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_cancel_nonexistent(self, mock_redis, engine):
        """取消不存在的算法"""
        result = await engine.cancel_algo("nonexist")
        assert result is False

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_cancel_all(self, mock_redis, engine):
        """Kill Switch 取消所有"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        for i in range(3):
            order = AlgoOrder(f"algo_{i}", "TWAP", "US.AAPL", "BUY", 1000)
            engine._orders[f"algo_{i}"] = order
        count = await engine.cancel_all()
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_all_algo_orders(self, engine):
        """获取所有算法订单"""
        engine._orders["a1"] = AlgoOrder("a1", "TWAP", "US.AAPL", "BUY", 1000)
        engine._orders["a2"] = AlgoOrder("a2", "VWAP", "US.TSLA", "SELL", 500)
        result = await engine.get_all_algo_orders()
        assert len(result) == 2

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_simulate_fill_sandbox(self, mock_redis, engine):
        """沙箱模式模拟成交"""
        mock_redis.get = AsyncMock(return_value=None)  # 非 LIVE 模式
        with patch("backend.services.algo_engine.futu_service", create=True) as mock_futu:
            mock_futu.get_quote = AsyncMock(return_value={"status": "success", "last_price": 150.0})
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                price = await engine._simulate_fill("US.AAPL", 100, "BUY")
        assert 149.0 < price < 151.0

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_simulate_fill_fallback(self, mock_redis, engine):
        """行情获取失败时返回默认 100.0"""
        mock_redis.get = AsyncMock(return_value=None)
        with patch("backend.services.algo_engine.futu_service", create=True) as mock_futu:
            mock_futu.get_quote = AsyncMock(side_effect=Exception("连接超时"))
            with patch.dict("sys.modules", {"backend.services.futu_service": MagicMock(futu_service=mock_futu)}):
                price = await engine._simulate_fill("US.AAPL", 100, "BUY")
        assert price == 100.0

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_save_algo_state_running(self, mock_redis, engine):
        """保存运行中状态到 Redis"""
        mock_redis.hset = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        await engine._save_algo_state(order)
        mock_redis.hset.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_save_algo_state_completed(self, mock_redis, engine):
        """完成状态从活动表移除"""
        mock_redis.hdel = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.status = "COMPLETED"
        await engine._save_algo_state(order)
        mock_redis.hdel.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_archive_algo(self, mock_redis, engine):
        """归档已完成算法"""
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.status = "COMPLETED"
        await engine._archive_algo(order)
        mock_redis.lpush.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_archive_algo_not_terminal(self, mock_redis, engine):
        """非终态不归档"""
        mock_redis.lpush = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.status = "RUNNING"
        await engine._archive_algo(order)
        mock_redis.lpush.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_restore_from_redis_empty(self, mock_redis, engine):
        """Redis 无数据时恢复 0 个"""
        mock_redis.hgetall = AsyncMock(return_value={})
        count = await engine.restore_from_redis()
        assert count == 0

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_restore_from_redis_with_data(self, mock_redis, engine):
        """从 Redis 恢复算法订单"""
        mock_redis.hgetall = AsyncMock(
            return_value={
                "algo_1": json.dumps(
                    {
                        "algo_type": "TWAP",
                        "symbol": "US.AAPL",
                        "side": "BUY",
                        "target_qty": 1000,
                        "status": "RUNNING",
                        "filled_qty": 200,
                        "avg_price": "150.00",
                    }
                )
            }
        )
        with patch.object(engine, "start_algo", new_callable=AsyncMock) as mock_start:
            mock_order = AlgoOrder("algo_new", "TWAP", "US.AAPL", "BUY", 1000)
            mock_start.return_value = mock_order
            count = await engine.restore_from_redis()
        assert count == 1

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_shutdown(self, mock_redis, engine):
        """优雅关停"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        engine._orders["a1"] = AlgoOrder("a1", "TWAP", "US.AAPL", "BUY", 1000)
        await engine.shutdown()
        assert engine._orders["a1"].status == "CANCELLED"


# ==========================================
# AlgoEngine 执行循环测试
# ==========================================
class TestAlgoEngineExecution:
    @pytest.fixture
    def engine(self):
        return AlgoEngine()

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_unsupported_type(self, mock_redis, engine):
        """不支持的算法类型"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "UNKNOWN", "US.AAPL", "BUY", 1000)
        engine._orders["algo_1"] = order
        await engine._run_algo_loop(order)
        assert order.status == "ERROR"
        assert "不支持" in order.message

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_twap_full_execution(self, mock_redis, engine):
        """完整 TWAP 执行循环"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 100)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_twap(order)
        assert order.filled_qty >= order.target_qty

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_vwap_full_execution(self, mock_redis, engine):
        """完整 VWAP 执行循环"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "VWAP", "US.AAPL", "BUY", 100)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_vwap(order)
        assert order.filled_qty >= order.target_qty

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_iceberg_full_execution(self, mock_redis, engine):
        """完整 ICEBERG 执行循环"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "ICEBERG", "US.AAPL", "BUY", 100)
        order.lot_size = 1
        order.iceberg_visible_qty = 20
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_iceberg(order)
        assert order.filled_qty >= order.target_qty

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_pov_full_execution(self, mock_redis, engine):
        """完整 POV 执行循环"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "POV", "US.AAPL", "BUY", 500)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_pov(order)
        assert order.filled_qty >= order.target_qty

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_is_full_execution(self, mock_redis, engine):
        """完整 IS 执行循环"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "IS", "US.AAPL", "BUY", 500)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_is(order)
        assert order.filled_qty >= order.target_qty

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_twap_already_filled(self, mock_redis, engine):
        """TWAP 已全部成交时直接返回"""
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 1000
        await engine._run_twap(order)
        assert order.filled_qty == 1000

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_vwap_already_filled(self, mock_redis, engine):
        """VWAP 已全部成交时直接返回"""
        order = AlgoOrder("algo_1", "VWAP", "US.AAPL", "BUY", 1000)
        order.filled_qty = 1000
        await engine._run_vwap(order)
        assert order.filled_qty == 1000

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_pov_already_filled(self, mock_redis, engine):
        """POV 已全部成交时直接返回"""
        order = AlgoOrder("algo_1", "POV", "US.AAPL", "BUY", 1000)
        order.filled_qty = 1000
        await engine._run_pov(order)
        assert order.filled_qty == 1000

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_is_already_filled(self, mock_redis, engine):
        """IS 已全部成交时直接返回"""
        order = AlgoOrder("algo_1", "IS", "US.AAPL", "BUY", 1000)
        order.filled_qty = 1000
        await engine._run_is(order)
        assert order.filled_qty == 1000

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_twap_stop_requested(self, mock_redis, engine):
        """TWAP 停止请求"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 1000)
        order._stop_requested = True
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            await engine._run_twap(order)
        assert order.filled_qty == 0

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_iceberg_stop_requested(self, mock_redis, engine):
        """ICEBERG 停止请求"""
        mock_redis.hset = AsyncMock()
        mock_redis.publish = AsyncMock()
        order = AlgoOrder("algo_1", "ICEBERG", "US.AAPL", "BUY", 1000)
        order._stop_requested = True
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            await engine._run_iceberg(order)
        assert order.filled_qty == 0

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_twap_dispatch(self, mock_redis, engine):
        """算法主循环分发到 TWAP"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "US.AAPL", "BUY", 50)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_algo_loop(order)
        assert order.status == "COMPLETED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_vwap_dispatch(self, mock_redis, engine):
        """算法主循环分发到 VWAP"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "VWAP", "US.AAPL", "BUY", 50)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_algo_loop(order)
        assert order.status == "COMPLETED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_iceberg_dispatch(self, mock_redis, engine):
        """算法主循环分发到 ICEBERG"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "ICEBERG", "US.AAPL", "BUY", 50)
        order.lot_size = 1
        order.iceberg_visible_qty = 10
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_algo_loop(order)
        assert order.status == "COMPLETED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_pov_dispatch(self, mock_redis, engine):
        """算法主循环分发到 POV"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "POV", "US.AAPL", "BUY", 200)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_algo_loop(order)
        assert order.status == "COMPLETED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_algo_loop_is_dispatch(self, mock_redis, engine):
        """算法主循环分发到 IS"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "IS", "US.AAPL", "BUY", 200)
        order.lot_size = 1
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=150.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_algo_loop(order)
        assert order.status == "COMPLETED"

    @pytest.mark.asyncio
    @patch("backend.services.algo_engine.redis_client")
    async def test_run_twap_hk_lot_size(self, mock_redis, engine):
        """港股整手 TWAP"""
        mock_redis.hset = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.publish = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()
        mock_redis.expire = AsyncMock()
        order = AlgoOrder("algo_1", "TWAP", "00700.HK", "BUY", 200)
        order.lot_size = 100  # 港股每手 100 股
        engine._orders["algo_1"] = order
        with patch.object(engine, "_simulate_fill", new_callable=AsyncMock, return_value=350.0):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await engine._run_twap(order)
        assert order.filled_qty >= order.target_qty
        # 确保每笔都是整手
        assert order.filled_qty % 100 == 0


# ===== TRADE-02 · 算法拆单增强测试 =====


class TestMarketImpactModelEnhanced:
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
class TestAlgoOrderEnhanced:
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
class TestAlgoEngineEnhanced:
    """AlgoEngine 核心引擎测试"""

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
class TestGetLotSizeEnhanced:
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
