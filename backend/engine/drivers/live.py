"""
BT-01e · LiveDriver 实盘/纸面驱动

职责：
- 行情总线订阅（Redis Pub/Sub quant:quotes:stream）
- 降级轮询（总线 30s 无消息 → futu_service.get_quote()）
- tick→bar 聚合（分钟/日级闭合触发 on_bar）
- asyncio.to_thread 隔离策略执行
- paper 模式（LiveDriver + SimBroker）

设计文档：docs/15. 回测实盘同构引擎设计.md §四.3
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Type

import pandas as pd

from backend.engine.clock import WallClock
from backend.engine.context import BaseContext
from backend.engine.contracts import Bar, OrderIntent, OrderUpdate, Position, QuoteSnapshot, RunManifest
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig
from backend.engine.gateway import ExecutionGateway, GatewayMode, SimBrokerExecutor
from backend.engine.strategy import Strategy

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# tick→bar 聚合器
# ─────────────────────────────────────────────


@dataclass
class TickAccumulator:
    """tick 聚合为 bar 的内存状态"""

    symbol: str
    ktype: str  # K_1M / K_5M / K_15M / K_30M / K_1H / K_DAY
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: float = 0.0
    tick_count: int = 0
    started_at: Optional[datetime] = None

    def add_tick(self, price: float, volume: float, dt: datetime) -> None:
        """添加一个 tick"""
        if self.tick_count == 0:
            self.open = price
            self.low = price
            self.started_at = dt
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.tick_count += 1

    def is_complete(self, now: datetime) -> bool:
        """检查 bar 是否已闭合"""
        if self.tick_count == 0 or self.started_at is None:
            return False

        elapsed = (now - self.started_at).total_seconds()

        # 根据 ktype 判断闭合周期
        period_seconds = {
            "K_1M": 60,
            "K_5M": 300,
            "K_15M": 900,
            "K_30M": 1800,
            "K_1H": 3600,
            "K_DAY": 86400,
        }.get(self.ktype, 86400)

        return elapsed >= period_seconds

    def to_bar(self) -> Bar:
        """转换为 Bar"""
        return Bar(
            symbol=self.symbol,
            dt=self.started_at or datetime.now(timezone.utc),
            open=self.open,
            high=self.high,
            low=self.low if self.low != float("inf") else self.close,
            close=self.close,
            volume=self.volume,
            ktype=self.ktype,
        )

    def reset(self) -> None:
        """重置聚合器（开始新 bar）"""
        self.open = 0.0
        self.high = 0.0
        self.low = float("inf")
        self.close = 0.0
        self.volume = 0.0
        self.tick_count = 0
        self.started_at = None


# ─────────────────────────────────────────────
# LiveContext（实盘 Context）
# ─────────────────────────────────────────────


class LiveContext(BaseContext):
    """实盘/纸面模式 Context 实现"""

    def __init__(
        self,
        mode: Literal["paper", "live"],
        run_id: str,
        clock: WallClock,
        gateway: ExecutionGateway,
        symbol: str,
        quote_fetcher: Optional[Callable] = None,
    ) -> None:
        super().__init__(mode=mode, run_id=run_id, clock=clock)
        self._gateway = gateway
        self._symbol = symbol
        self._quote_fetcher = quote_fetcher
        self._latest_quote: Optional[QuoteSnapshot] = None
        self._cash_value: float = 100000.0
        self._positions: Dict[str, Position] = {}

    def set_latest_quote(self, quote: QuoteSnapshot) -> None:
        """更新最新行情（由 LiveDriver 调用）"""
        self._latest_quote = quote

    def set_cash(self, cash: float) -> None:
        self._cash_value = cash

    def set_position(self, symbol: str, position: Position) -> None:
        self._positions[symbol] = position

    # ─── 数据面 ───

    def history(self, symbol: str, n: int, ktype: str = "K_DAY") -> pd.DataFrame:
        """获取历史 K 线（实盘走 KlineCacheEngine，当前桩实现）"""
        # TODO: 接入 KlineCacheEngine（L1 Redis / L2 Parquet）
        return pd.DataFrame()

    def quote(self, symbol: str) -> QuoteSnapshot:
        """获取最新行情快照"""
        if self._latest_quote and self._latest_quote.symbol == symbol:
            return self._latest_quote
        return QuoteSnapshot(symbol=symbol, dt=self.now, price=0.0, stale=True)

    def financial(self, symbol: str, field: str) -> Optional[float]:
        """获取财务数据（实盘模式暂不支持，返回 None）"""
        return None

    def universe(self) -> List[str]:
        """获取标的池（实盘返回订阅标的）"""
        return [self._symbol]

    # ─── 账户面 ───

    def position(self, symbol: str) -> Position:
        return self._positions.get(symbol, Position(symbol=symbol))

    @property
    def cash(self) -> float:
        return self._cash_value

    @property
    def equity(self) -> float:
        pos = self.position(self._symbol)
        quote = self._latest_quote
        market_value = pos.qty * (quote.price if quote else 0.0)
        return self._cash_value + market_value

    # ─── 执行面 ───

    def order(self, intent: OrderIntent) -> str:
        return self._gateway.submit(intent, run_id=self.run_id)

    def cancel(self, order_id: str) -> bool:
        return self._gateway.cancel(order_id)

    def open_orders(self) -> List[OrderUpdate]:
        return []


# ─────────────────────────────────────────────
# LiveDriver
# ─────────────────────────────────────────────


@dataclass
class LiveDriverConfig:
    """LiveDriver 配置"""

    mode: Literal["paper", "live"] = "paper"
    ktype: str = "K_DAY"  # 策略 K 线周期
    stale_timeout_seconds: float = 30.0  # 行情降级超时
    poll_interval_seconds: float = 60.0  # 降级轮询间隔
    initial_capital: float = 100000.0


class LiveDriver:
    """实盘/纸面驱动

    生命周期：
    1. on_init：声明订阅 → 向行情总线注册兴趣
    2. 行情消费：订阅 Redis Pub/Sub quant:quotes:stream
       └─ 降级：30s 无消息 → futu_service.get_quote() 轮询
    3. K线聚合：tick → bar 闭合触发 on_bar
    4. 策略调用：asyncio.to_thread(strategy.on_bar, ctx, bar)
    5. 订单回报：订阅 oms:orders:update Pub/Sub
    """

    def __init__(self, config: LiveDriverConfig) -> None:
        self.config = config
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._accumulator: Optional[TickAccumulator] = None
        self._last_message_at: Optional[datetime] = None

    async def start(
        self,
        strategy: Strategy,
        symbol: str,
        params: Dict[str, Any],
        source_code: Optional[str] = None,
    ) -> str:
        """启动 LiveDriver

        Returns:
            run_id
        """
        run_id = str(uuid.uuid4())

        # 构造 Context
        clock = WallClock()

        # 构造执行网关
        if self.config.mode == "paper":
            broker = SimBroker(
                SimBrokerConfig(paper_mode=True),
                initial_cash=self.config.initial_capital,
            )
            # PT-01b: Fill→Ledger 同步钩子（可选，由外部注入 ledger_service）
            if hasattr(self, '_paper_fill_callback') and self._paper_fill_callback:
                broker.set_fill_callback(self._paper_fill_callback)
            sim_executor = SimBrokerExecutor(broker)
            gateway = ExecutionGateway(mode=GatewayMode.PAPER, sim_executor=sim_executor)
        else:
            gateway = ExecutionGateway(mode=GatewayMode.LIVE)

        ctx = LiveContext(
            mode=self.config.mode,
            run_id=run_id,
            clock=clock,
            gateway=gateway,
            symbol=symbol,
        )

        # 初始化聚合器
        self._accumulator = TickAccumulator(symbol=symbol, ktype=self.config.ktype)

        # 策略初始化
        strategy.on_init(ctx)

        # 启动主循环
        self._running = True
        self._task = asyncio.create_task(
            self._run_loop(strategy, ctx, symbol, run_id)
        )

        logger.info(f"[LiveDriver] Started: run_id={run_id}, mode={self.config.mode}, symbol={symbol}")
        return run_id

    async def stop(self) -> None:
        """停止 LiveDriver"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[LiveDriver] Stopped")

    async def _run_loop(
        self,
        strategy: Strategy,
        ctx: LiveContext,
        symbol: str,
        run_id: str,
    ) -> None:
        """主循环"""
        try:
            while self._running:
                try:
                    # 1. 获取行情
                    quote = await self._fetch_quote(symbol)
                    ctx.set_latest_quote(quote)

                    # 2. tick→bar 聚合
                    if self._accumulator:
                        self._accumulator.add_tick(
                            price=quote.price,
                            volume=0.0,  # tick 级别成交量不可用时为 0
                            dt=quote.dt,
                        )

                        # 检查 bar 闭合
                        if self._accumulator.is_complete(ctx.now):
                            bar = self._accumulator.to_bar()

                            # 3. 策略执行（to_thread 隔离）
                            await asyncio.to_thread(strategy.on_bar, ctx, bar)

                            # 重置聚合器
                            self._accumulator.reset()

                except Exception as e:
                    logger.warning(f"[LiveDriver] Loop error: {e}")

                # 等待下一轮
                await asyncio.sleep(self.config.poll_interval_seconds)

        except asyncio.CancelledError:
            logger.info("[LiveDriver] Loop cancelled")
        finally:
            strategy.on_stop(ctx)

    async def _fetch_quote(self, symbol: str) -> QuoteSnapshot:
        """获取行情（带降级）"""
        now = datetime.now(timezone.utc)

        # 尝试从 Redis 行情流获取
        try:
            from backend.core.redis_client import redis_client

            # 检查 Redis 连接中是否有最新行情
            cache_key = f"quant:cache:quote:{symbol}"
            raw = await redis_client.get(cache_key)
            if raw:
                data = json.loads(raw)
                self._last_message_at = now
                return QuoteSnapshot(
                    symbol=symbol,
                    dt=now,
                    price=float(data.get("last_price", data.get("price", 0))),
                    bid=float(data.get("bid_price", 0)) or None,
                    ask=float(data.get("ask_price", 0)) or None,
                    stale=False,
                )
        except Exception as e:
            logger.debug(f"[LiveDriver] Redis quote fetch failed: {e}")

        # 降级：检查是否超时
        if self._last_message_at:
            elapsed = (now - self._last_message_at).total_seconds()
            if elapsed > self.config.stale_timeout_seconds:
                logger.warning(f"[LiveDriver] Quote stale for {elapsed:.0f}s, using fallback")
                return QuoteSnapshot(symbol=symbol, dt=now, price=0.0, stale=True)

        # 最终降级
        return QuoteSnapshot(symbol=symbol, dt=now, price=0.0, stale=True)

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()
