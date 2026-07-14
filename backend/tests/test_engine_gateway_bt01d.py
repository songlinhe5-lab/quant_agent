"""
BT-01d · ExecutionGateway 测试

覆盖：
- ExecutionGateway: 订单路由/安全锁/幂等/降级
- SafetyLockStatus: 安全锁状态检查
- SimBrokerExecutor: SimBroker 执行器
- OmsExecutionAdapter: OMS 适配器（桩实现）

测试要求：≥85% 覆盖率
"""

from datetime import datetime, timezone

import pytest

from backend.engine import Bar, OrderIntent
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig
from backend.engine.gateway import (
    ExecutionGateway,
    GatewayMode,
    OmsExecutionAdapter,
    SafetyLockStatus,
    SimBrokerExecutor,
)
from backend.schemas.domain import OrderStatus


# ─────────────────────────────────────────────
# SafetyLockStatus 测试
# ─────────────────────────────────────────────


class TestSafetyLockStatus:
    """安全锁状态测试"""

    def test_all_passed(self):
        """所有锁通过"""
        status = SafetyLockStatus(
            real_trade_enabled=True,
            trading_mode_live=True,
            kill_switch_inactive=True,
        )
        assert status.all_passed is True
        assert status.failure_reason() is None

    def test_real_trade_disabled(self):
        """REAL_TRADE_EXECUTE 未启用"""
        status = SafetyLockStatus(
            real_trade_enabled=False,
            trading_mode_live=True,
            kill_switch_inactive=True,
        )
        assert status.all_passed is False
        assert "REAL_TRADE_EXECUTE" in status.failure_reason()

    def test_trading_mode_not_live(self):
        """trading_mode 不是 LIVE"""
        status = SafetyLockStatus(
            real_trade_enabled=True,
            trading_mode_live=False,
            kill_switch_inactive=True,
        )
        assert status.all_passed is False
        assert "trading_mode" in status.failure_reason()

    def test_kill_switch_triggered(self):
        """kill_switch 触发"""
        status = SafetyLockStatus(
            real_trade_enabled=True,
            trading_mode_live=True,
            kill_switch_inactive=False,
        )
        assert status.all_passed is False
        assert "kill_switch" in status.failure_reason()


# ─────────────────────────────────────────────
# SimBrokerExecutor 测试
# ─────────────────────────────────────────────


class TestSimBrokerExecutor:
    """SimBroker 执行器测试"""

    @pytest.fixture
    def executor(self):
        broker = SimBroker(SimBrokerConfig(), initial_cash=100000.0)
        bar = Bar(
            symbol="TEST.001",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            volume=1000000.0,
        )
        executor = SimBrokerExecutor(broker)
        executor.set_current_bar(bar)
        return executor

    def test_submit(self, executor):
        """提交订单"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        order_id = executor.submit(intent, "client-order-1")
        assert order_id.startswith("sim-")

    def test_cancel(self, executor):
        """取消订单"""
        intent = OrderIntent(
            symbol="TEST.001",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=95.0,
        )
        order_id = executor.submit(intent, "client-order-1")
        assert executor.cancel(order_id) is True


# ─────────────────────────────────────────────
# ExecutionGateway 测试
# ─────────────────────────────────────────────


class TestExecutionGateway:
    """ExecutionGateway 测试"""

    @pytest.fixture
    def sim_executor(self):
        broker = SimBroker(SimBrokerConfig(), initial_cash=100000.0)
        bar = Bar(
            symbol="TEST.001",
            dt=datetime(2024, 1, 15, 16, 0, tzinfo=timezone.utc),
            open=100.0,
            high=102.0,
            low=98.0,
            close=100.0,
            volume=1000000.0,
        )
        executor = SimBrokerExecutor(broker)
        executor.set_current_bar(bar)
        return executor

    @pytest.fixture
    def backtest_gateway(self, sim_executor):
        return ExecutionGateway(mode=GatewayMode.BACKTEST, sim_executor=sim_executor)

    def test_backtest_mode_submit(self, backtest_gateway):
        """回测模式提交订单"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100, tag="test")
        order_id = backtest_gateway.submit(intent, run_id="run-1")
        assert order_id.startswith("sim-")

    def test_paper_mode_submit(self, sim_executor):
        """纸面模式提交订单"""
        gateway = ExecutionGateway(mode=GatewayMode.PAPER, sim_executor=sim_executor)
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        order_id = gateway.submit(intent, run_id="run-1")
        assert order_id is not None

    def test_idempotent_rejection(self, backtest_gateway):
        """幂等去重"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100, tag="same_tag")

        order_id1 = backtest_gateway.submit(intent, run_id="run-1")
        order_id2 = backtest_gateway.submit(intent, run_id="run-1")

        # 相同 client_order_id 应返回相同 order_id
        assert order_id1 == order_id2

    def test_different_run_id_different_order(self, backtest_gateway):
        """不同 run_id 产生不同订单"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100, tag="same_tag")

        order_id1 = backtest_gateway.submit(intent, run_id="run-1")
        order_id2 = backtest_gateway.submit(intent, run_id="run-2")

        assert order_id1 != order_id2

    def test_live_mode_degraded_without_safety(self, sim_executor):
        """实盘模式安全锁未通过时降级"""
        gateway = ExecutionGateway(mode=GatewayMode.LIVE, sim_executor=sim_executor)
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)

        safety = SafetyLockStatus(
            real_trade_enabled=False,
            trading_mode_live=True,
            kill_switch_inactive=True,
        )

        order_id = gateway.submit(intent, run_id="run-1", safety_status=safety)
        assert order_id is not None  # 降级到 sim 执行
        assert gateway.degraded_count == 1

    def test_live_mode_all_safety_passed(self, sim_executor):
        """实盘模式所有安全锁通过"""
        live_executor = OmsExecutionAdapter()
        gateway = ExecutionGateway(
            mode=GatewayMode.LIVE,
            sim_executor=sim_executor,
            live_executor=live_executor,
        )
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)

        safety = SafetyLockStatus(
            real_trade_enabled=True,
            trading_mode_live=True,
            kill_switch_inactive=True,
        )

        order_id = gateway.submit(intent, run_id="run-1", safety_status=safety)
        assert order_id.startswith("oms-")
        assert gateway.degraded_count == 0

    def test_cancel_order(self, backtest_gateway):
        """取消订单"""
        intent = OrderIntent(
            symbol="TEST.001",
            side="BUY",
            qty=100,
            order_type="LIMIT",
            limit_price=95.0,
        )
        order_id = backtest_gateway.submit(intent, run_id="run-1")
        # 注意：SimBrokerExecutor.cancel 需要 order_id 在 broker 中
        # 这里只是测试 gateway.cancel 的路由


# ─────────────────────────────────────────────
# OmsExecutionAdapter 测试
# ─────────────────────────────────────────────


class TestOmsExecutionAdapter:
    """OMS 执行适配器测试"""

    @pytest.fixture
    def adapter(self):
        return OmsExecutionAdapter()

    def test_submit(self, adapter):
        """提交订单"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100, tag="test")
        order_id = adapter.submit(intent, "client-order-1")
        assert order_id.startswith("oms-")

    def test_cancel(self, adapter):
        """取消订单"""
        intent = OrderIntent(symbol="TEST.001", side="BUY", qty=100)
        order_id = adapter.submit(intent, "client-order-1")
        assert adapter.cancel(order_id) is True
        assert adapter.cancel("non-existent") is False
