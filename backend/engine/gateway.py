"""
BT-01d · ExecutionGateway 统一订单出口

职责：
- 订单路由：backtest/paper → SimBroker，live → OmsExecutionAdapter
- 三级安全锁：REAL_TRADE_EXECUTE + trading_mode + kill_switch
- 幂等去重：client_order_id = tag + run_id
- 降级路径：安全锁未通过时降级为 paper 语义

设计文档：docs/15. 回测实盘同构引擎设计.md §五
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, Protocol

from backend.engine.contracts import OrderIntent, OrderUpdate
from backend.schemas.domain import OrderStatus

if TYPE_CHECKING:
    from backend.engine.drivers.sim_broker import SimBroker

logger = logging.getLogger(__name__)


class GatewayMode(str, Enum):
    """网关模式"""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class SafetyLockStatus:
    """安全锁状态"""

    real_trade_enabled: bool  # REAL_TRADE_EXECUTE 环境变量
    trading_mode_live: bool  # quant:oms:trading_mode == LIVE
    kill_switch_inactive: bool  # oms:kill_switch 未触发

    @property
    def all_passed(self) -> bool:
        """所有安全锁通过"""
        return self.real_trade_enabled and self.trading_mode_live and self.kill_switch_inactive

    def failure_reason(self) -> Optional[str]:
        """返回失败原因"""
        if not self.real_trade_enabled:
            return "REAL_TRADE_EXECUTE not enabled"
        if not self.trading_mode_live:
            return "trading_mode is not LIVE"
        if not self.kill_switch_inactive:
            return "kill_switch is triggered"
        return None


class OrderExecutor(Protocol):
    """订单执行器协议"""

    def submit(self, intent: OrderIntent, client_order_id: str) -> str:
        """提交订单，返回 order_id"""
        ...

    def cancel(self, order_id: str) -> bool:
        """取消订单"""
        ...


class SimBrokerExecutor:
    """SimBroker 执行器（回测/纸面模式）"""

    def __init__(self, broker: "SimBroker", current_bar=None):
        self._broker = broker
        self._current_bar = current_bar

    def set_current_bar(self, bar) -> None:
        self._current_bar = bar

    def submit(self, intent: OrderIntent, client_order_id: str) -> str:
        if self._current_bar is None:
            raise RuntimeError("SimBrokerExecutor requires current_bar for market orders")
        return self._broker.submit(intent, self._current_bar)

    def cancel(self, order_id: str) -> bool:
        return self._broker.cancel(order_id)


class ExecutionGateway:
    """统一订单出口

    所有 OrderIntent 必须经过 Gateway 路由到正确的执行后端。
    """

    def __init__(
        self,
        mode: GatewayMode,
        sim_executor: Optional[SimBrokerExecutor] = None,
        live_executor: Optional["OmsExecutionAdapter"] = None,
    ) -> None:
        self.mode = mode
        self._sim_executor = sim_executor
        self._live_executor = live_executor
        self._submitted_orders: dict[str, OrderUpdate] = {}  # client_order_id -> OrderUpdate
        self._degraded_count = 0  # 降级计数

    def submit(
        self,
        intent: OrderIntent,
        run_id: str,
        safety_status: Optional[SafetyLockStatus] = None,
    ) -> str:
        """提交订单

        Args:
            intent: 订单意图
            run_id: 运行 ID（用于生成 client_order_id）
            safety_status: 安全锁状态（仅 live 模式需要）

        Returns:
            order_id
        """
        # 生成幂等 client_order_id
        client_order_id = self._make_client_order_id(intent, run_id)

        # 幂等检查
        if client_order_id in self._submitted_orders:
            logger.warning(f"[Gateway] Duplicate order rejected: {client_order_id}")
            return self._submitted_orders[client_order_id].order_id

        # 路由到执行后端
        if self.mode in (GatewayMode.BACKTEST, GatewayMode.PAPER):
            return self._submit_to_sim(intent, client_order_id)
        elif self.mode == GatewayMode.LIVE:
            return self._submit_to_live(intent, client_order_id, safety_status)
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def _submit_to_sim(self, intent: OrderIntent, client_order_id: str) -> str:
        """提交到 SimBroker（回测/纸面模式）"""
        if self._sim_executor is None:
            raise RuntimeError("SimBrokerExecutor not configured")

        order_id = self._sim_executor.submit(intent, client_order_id)
        self._submitted_orders[client_order_id] = OrderUpdate(
            order_id=order_id,
            intent_tag=intent.tag,
            status=OrderStatus.SUBMITTED,
        )
        return order_id

    def _submit_to_live(
        self,
        intent: OrderIntent,
        client_order_id: str,
        safety_status: Optional[SafetyLockStatus],
    ) -> str:
        """提交到实盘（带安全锁检查）"""
        # 安全锁检查
        if safety_status is None or not safety_status.all_passed:
            reason = safety_status.failure_reason() if safety_status else "safety_status is None"
            logger.warning(f"[Gateway] [SANDBOX] Live order degraded: {reason}")
            self._degraded_count += 1
            # 降级为 paper 语义
            return self._submit_to_sim(intent, client_order_id)

        # 安全锁通过，提交到实盘
        if self._live_executor is None:
            raise RuntimeError("OmsExecutionAdapter not configured for live mode")

        order_id = self._live_executor.submit(intent, client_order_id)
        self._submitted_orders[client_order_id] = OrderUpdate(
            order_id=order_id,
            intent_tag=intent.tag,
            status=OrderStatus.SUBMITTED,
        )
        return order_id

    def cancel(self, order_id: str) -> bool:
        """取消订单"""
        if self.mode in (GatewayMode.BACKTEST, GatewayMode.PAPER):
            if self._sim_executor:
                return self._sim_executor.cancel(order_id)
        elif self.mode == GatewayMode.LIVE:
            if self._live_executor:
                return self._live_executor.cancel(order_id)
        return False

    def _make_client_order_id(self, intent: OrderIntent, run_id: str) -> str:
        """生成幂等 client_order_id"""
        tag = intent.tag or "untagged"
        raw = f"{run_id}:{intent.symbol}:{intent.side}:{tag}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def degraded_count(self) -> int:
        """降级订单计数"""
        return self._degraded_count


# ─────────────────────────────────────────────
# OmsExecutionAdapter（实盘适配器）
# ─────────────────────────────────────────────


class OmsExecutionAdapter:
    """OMS 实盘执行适配器

    职责：
    - OrderIntent → oms_service.create_order()
    - futu.place_order() 通过 asyncio.to_thread 隔离
    - 状态回写 + 发布 oms:orders:update

    注意：实际实现需要注入 oms_service 和 futu_service。
    """

    def __init__(
        self,
        oms_service=None,
        futu_service=None,
    ) -> None:
        self._oms_service = oms_service
        self._futu_service = futu_service
        self._orders: dict[str, OrderUpdate] = {}

    def submit(self, intent: OrderIntent, client_order_id: str) -> str:
        """提交订单到 OMS

        当前为桩实现，实际应调用 oms_service.create_order() + futu.place_order()
        """
        import uuid

        order_id = f"oms-{uuid.uuid4().hex[:8]}"

        # TODO: 实际实现
        # 1. oms_service.create_order(symbol, side, qty, order_type, limit_price)
        # 2. asyncio.to_thread(futu_service.place_order, ...)
        # 3. 状态回写

        self._orders[order_id] = OrderUpdate(
            order_id=order_id,
            intent_tag=intent.tag,
            status=OrderStatus.SUBMITTED,
        )

        logger.info(f"[OmsAdapter] Order submitted: {order_id} for {intent.symbol}")
        return order_id

    def cancel(self, order_id: str) -> bool:
        """取消订单

        当前为桩实现。
        """
        if order_id in self._orders:
            self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False
