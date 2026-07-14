"""
BT-01b · SimBroker 模拟撮合引擎

从 EventDrivenBacktestEngine 抽取撮合逻辑，保持回测结果与现网可对账。
职责：
- 限价单挂单/撮合
- 止损单触发
- 滑点 + 手续费计算
- 持仓/现金管理

设计文档：docs/15. 回测实盘同构引擎设计.md §四.1
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Dict, List, Optional

from backend.engine.contracts import Bar, OrderIntent, OrderUpdate, Position
from backend.schemas.domain import OrderStatus

if TYPE_CHECKING:
    from backend.engine.strategy import Strategy


@dataclass
class PendingOrder:
    """挂单簿条目"""

    order_id: str
    intent: OrderIntent
    placed_at: datetime
    tag: Optional[str] = None


@dataclass
class SimBrokerConfig:
    """SimBroker 配置"""

    commission_pct: float = 0.0005  # 手续费率
    slippage_pct: float = 0.001  # 滑点率
    paper_mode: bool = False  # PT-01b: paper 模式启用差异化行为


@dataclass
class SimBrokerState:
    """SimBroker 内部状态"""

    cash: float = 100000.0
    positions: Dict[str, int] = field(default_factory=dict)  # symbol -> qty
    avg_costs: Dict[str, float] = field(default_factory=dict)  # symbol -> avg_cost
    pending_orders: List[PendingOrder] = field(default_factory=list)
    total_friction: float = 0.0
    trades: List[Dict] = field(default_factory=list)


class SimBroker:
    """模拟撮合引擎

    撮合语义：
    - 市价单：立即以当前 bar 收盘价 ± 滑点成交
    - 限价单：挂入 pending_orders，后续 bar 检查是否触发
    - 止损单：在 on_bar 开始时检查（用 bar 高低价）
    """

    def __init__(self, config: SimBrokerConfig, initial_cash: float = 100000.0) -> None:
        self.config = config
        self.state = SimBrokerState(cash=initial_cash)
        self._initial_cash = initial_cash
        self._pending_fills: List[OrderUpdate] = []  # 待分发的成交回报
        self._fill_callback = None  # PT-01b: paper 模式成交回调 -> PaperLedgerService

    def set_fill_callback(self, callback) -> None:
        """PT-01b: 设置 paper 模式成交回调（用于 Fill→Ledger 同步）"""
        self._fill_callback = callback

    # ─── 核心撮合接口 ───

    def submit(self, intent: OrderIntent, current_bar: Bar) -> str:
        """提交订单意图

        Returns:
            order_id (paper_mode 下可能返回 REJECTED_* 字符串)
        """
        # PT-01b: paper 模式前置检查
        if self.config.paper_mode:
            # stale 行情拒单
            if hasattr(current_bar, 'stale') and current_bar.stale:
                return "REJECTED_STALE"
            # 交易时段检查
            from backend.services.market_correctness import MarketSession
            if not MarketSession.is_trading_hours(intent.symbol, current_bar.dt):
                return "REJECTED_MARKET_CLOSED"

        order_id = f"sim-{uuid.uuid4().hex[:8]}"

        if intent.order_type == "MARKET":
            # 市价单立即撮合
            self._execute_market(intent, current_bar, order_id)
        elif intent.order_type == "LIMIT":
            # 限价单挂入订单簿
            pending = PendingOrder(
                order_id=order_id,
                intent=intent,
                placed_at=current_bar.dt,
                tag=intent.tag,
            )
            self.state.pending_orders.append(pending)

        return order_id

    def match_open_orders(self, bar: Bar) -> None:
        """撮合挂单簿（在策略 on_bar 之前调用）

        用当前 bar 的高低价检查限价单是否可成交。
        """
        filled_indices = []

        for idx, pending in enumerate(self.state.pending_orders):
            intent = pending.intent
            if intent.symbol != bar.symbol:
                continue

            if intent.side == "BUY" and intent.limit_price is not None:
                # 买入限价单：当前最低价 <= 限价 → 成交
                if bar.low <= intent.limit_price:
                    exec_price = min(intent.limit_price, bar.open)
                    self._fill_buy(intent, exec_price, bar.dt, pending.order_id)
                    filled_indices.append(idx)

            elif intent.side == "SELL" and intent.limit_price is not None:
                # 卖出限价单：当前最高价 >= 限价 → 成交
                if bar.high >= intent.limit_price:
                    exec_price = max(intent.limit_price, bar.open)
                    self._fill_sell(intent, exec_price, bar.dt, pending.order_id)
                    filled_indices.append(idx)

        # 移除已成交的挂单（倒序删除避免索引偏移）
        for idx in sorted(filled_indices, reverse=True):
            self.state.pending_orders.pop(idx)

    def check_stop_loss(self, bar: Bar) -> Optional[str]:
        """检查止损单（在策略 on_bar 之前调用）

        Returns:
            触发的 order_id，或 None
        """
        for pending in list(self.state.pending_orders):
            intent = pending.intent
            if intent.symbol != bar.symbol or intent.stop_loss is None:
                continue

            pos_qty = self.state.positions.get(bar.symbol, 0)

            # 多头止损：当前最低价 <= 止损价 → 触发
            if intent.side == "SELL" and pos_qty > 0:
                if bar.low <= intent.stop_loss:
                    exec_price = max(intent.stop_loss, bar.open)
                    self._fill_sell(intent, exec_price, bar.dt, pending.order_id)
                    self.state.pending_orders.remove(pending)
                    return pending.order_id

        return None

    def dispatch_fills(self, strategy: "Strategy", ctx: object) -> None:
        """分发成交回报给策略"""
        for update in self._pending_fills:
            strategy.on_order_update(ctx, update)
        self._pending_fills.clear()

    # ─── 账户查询 ───

    def get_position(self, symbol: str) -> Position:
        """获取持仓"""
        qty = self.state.positions.get(symbol, 0)
        avg_cost = self.state.avg_costs.get(symbol, 0.0)
        return Position(symbol=symbol, qty=qty, avg_cost=avg_cost)

    @property
    def cash(self) -> float:
        return self.state.cash

    def get_open_orders(self, symbol: Optional[str] = None) -> List[PendingOrder]:
        """获取挂单"""
        if symbol:
            return [o for o in self.state.pending_orders if o.intent.symbol == symbol]
        return self.state.pending_orders.copy()

    # ─── 内部撮合逻辑 ───

    def _execute_market(self, intent: OrderIntent, bar: Bar, order_id: str) -> None:
        """市价单撮合"""
        base_price = bar.close

        if intent.side == "BUY":
            exec_price = base_price * (1 + self.config.slippage_pct)
            self._fill_buy(intent, exec_price, bar.dt, order_id)
        elif intent.side == "SELL":
            exec_price = base_price * (1 - self.config.slippage_pct)
            self._fill_sell(intent, exec_price, bar.dt, order_id)

    def _fill_buy(self, intent: OrderIntent, exec_price: float, dt: datetime, order_id: str) -> None:
        """买入成交"""
        turnover = intent.qty * exec_price
        fee = turnover * self.config.commission_pct

        if turnover + fee > self.state.cash:
            # 资金不足，按可用资金计算
            affordable = int(self.state.cash / (exec_price * (1 + self.config.commission_pct)))
            if affordable <= 0:
                return
            intent = intent.model_copy(update={"qty": affordable})
            turnover = affordable * exec_price
            fee = turnover * self.config.commission_pct

        self.state.cash -= turnover + fee
        self.state.total_friction += fee + (intent.qty * exec_price * self.config.slippage_pct)

        # 更新持仓
        old_qty = self.state.positions.get(intent.symbol, 0)
        old_cost = self.state.avg_costs.get(intent.symbol, 0.0)
        new_qty = old_qty + intent.qty
        new_cost = (old_cost * old_qty + exec_price * intent.qty) / new_qty if new_qty > 0 else 0.0
        self.state.positions[intent.symbol] = new_qty
        self.state.avg_costs[intent.symbol] = new_cost

        # 记录成交
        self.state.trades.append({
            "date": dt.isoformat(),
            "symbol": intent.symbol,
            "action": "BUY",
            "price": round(exec_price, 4),
            "shares": intent.qty,
            "fee": round(fee, 4),
        })

        # 生成交割回报
        self._pending_fills.append(OrderUpdate(
            order_id=order_id,
            intent_tag=intent.tag,
            status=OrderStatus.FILLED,
            filled_qty=intent.qty,
            avg_fill_price=exec_price,
        ))

        # PT-01b: paper 模式成交回调
        if self.config.paper_mode and self._fill_callback:
            self._fill_callback({
                "order_id": order_id,
                "symbol": intent.symbol,
                "side": "BUY",
                "qty": intent.qty,
                "price": exec_price,
                "commission": fee,
                "slippage": intent.qty * exec_price * self.config.slippage_pct,
                "intent_tag": intent.tag,
                "dt": dt,
            })

    def _fill_sell(self, intent: OrderIntent, exec_price: float, dt: datetime, order_id: str) -> None:
        """卖出成交"""
        pos_qty = self.state.positions.get(intent.symbol, 0)
        if pos_qty <= 0:
            return

        sell_qty = min(intent.qty, pos_qty)
        turnover = sell_qty * exec_price
        fee = turnover * self.config.commission_pct

        self.state.cash += turnover - fee
        self.state.total_friction += fee + (sell_qty * exec_price * self.config.slippage_pct)

        # 更新持仓
        self.state.positions[intent.symbol] = pos_qty - sell_qty
        if self.state.positions[intent.symbol] == 0:
            self.state.avg_costs.pop(intent.symbol, None)

        # 计算盈亏
        avg_cost = self.state.avg_costs.get(intent.symbol, exec_price)
        profit = (exec_price - avg_cost) * sell_qty - fee

        # 记录成交
        self.state.trades.append({
            "date": dt.isoformat(),
            "symbol": intent.symbol,
            "action": "SELL",
            "price": round(exec_price, 4),
            "shares": sell_qty,
            "fee": round(fee, 4),
            "profit": round(profit, 4),
        })

        # 生成交割回报
        self._pending_fills.append(OrderUpdate(
            order_id=order_id,
            intent_tag=intent.tag,
            status=OrderStatus.FILLED,
            filled_qty=sell_qty,
            avg_fill_price=exec_price,
        ))

        # PT-01b: paper 模式成交回调
        if self.config.paper_mode and self._fill_callback:
            self._fill_callback({
                "order_id": order_id,
                "symbol": intent.symbol,
                "side": "SELL",
                "qty": sell_qty,
                "price": exec_price,
                "commission": fee,
                "slippage": sell_qty * exec_price * self.config.slippage_pct,
                "intent_tag": intent.tag,
                "dt": dt,
            })

    def cancel(self, order_id: str) -> bool:
        """取消挂单"""
        for i, pending in enumerate(self.state.pending_orders):
            if pending.order_id == order_id:
                self.state.pending_orders.pop(i)
                return True
        return False
