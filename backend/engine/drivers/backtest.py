"""
BT-01b · BacktestDriver 回测驱动

职责：
- 历史 K 线回放主循环
- SimClock 逐 bar 推进
- 撮合顺序：先撮合挂单/止损 → 再驱动策略 → 分发成交回报
- RunManifest 填充（code_hash / seed）
- history() 返回截至当前 bar 的窗口视图

设计文档：docs/15. 回测实盘同构引擎设计.md §四.1
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

import numpy as np
import pandas as pd

from backend.engine.clock import SimClock
from backend.engine.context import BaseContext
from backend.engine.contracts import Bar, OrderIntent, OrderUpdate, Position, QuoteSnapshot, RunManifest
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig
from backend.engine.strategy import Strategy

if TYPE_CHECKING:
    from backend.services.financial_pit import PointInTimeStore
    from backend.services.survivorship_bias import SurvivorshipBiasTracker


@dataclass
class BacktestConfig:
    """回测配置"""

    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    random_seed: Optional[int] = None
    data_snapshot_id: Optional[str] = None
    manifest_hash: Optional[str] = None  # 显式绑定；或由 SnapshotResolver 填充
    data_mode: Optional[str] = None  # snapshot | live | unbound


@dataclass
class BacktestResult:
    """回测结果"""

    metrics: Dict[str, Any]
    equity_curve: List[Dict[str, Any]]
    trades: List[Dict[str, Any]]
    debug_logs: List[str]
    manifest: RunManifest


class BacktestContext(BaseContext):
    """回测专用 Context 实现

    注入 K 线数据 + SimBroker + PIT/Universe 可选依赖。
    """

    def __init__(
        self,
        run_id: str,
        clock: SimClock,
        df: pd.DataFrame,
        symbol: str,
        broker: SimBroker,
        pit_store: Optional["PointInTimeStore"] = None,
        universe_tracker: Optional["SurvivorshipBiasTracker"] = None,
    ) -> None:
        super().__init__(mode="backtest", run_id=run_id, clock=clock)
        self._df = df
        self._symbol = symbol
        self._broker = broker
        self._pit_store = pit_store
        self._universe_tracker = universe_tracker
        self._cursor: int = 0  # 当前 bar 索引

    def set_cursor(self, idx: int) -> None:
        """设置当前 bar 索引（由 Driver 调用）"""
        self._cursor = idx

    # ─── 数据面 ───

    def history(self, symbol: str, n: int, ktype: str = "K_DAY") -> pd.DataFrame:
        """获取截至当前 bar 的历史 K 线（最近 n 根）"""
        if symbol != self._symbol:
            return pd.DataFrame()
        end = self._cursor + 1
        start = max(0, end - n)
        return self._df.iloc[start:end].copy()

    def quote(self, symbol: str) -> QuoteSnapshot:
        """获取当前 bar 的行情快照"""
        if symbol != self._symbol or self._cursor >= len(self._df):
            return QuoteSnapshot(symbol=symbol, dt=self.now, price=0.0, stale=True)
        row = self._df.iloc[self._cursor]
        return QuoteSnapshot(
            symbol=symbol,
            dt=self.now,
            price=float(row.get("close", 0.0)),
            bid=float(row.get("close", 0.0)),
            ask=float(row.get("close", 0.0)),
        )

    def financial(self, symbol: str, field: str) -> Optional[float]:
        """获取财务数据（Point-in-Time，as-of ctx.now）"""
        if self._pit_store is None:
            return None
        from backend.services.financial_pit import PITQuery

        query = PITQuery(symbol=symbol, field=field, as_of_date=self.now.date())
        points = self._pit_store.query_as_of(query)
        if not points:
            return None
        return points[-1].value

    def universe(self) -> List[str]:
        """获取当前时点的标的池"""
        if self._universe_tracker is None:
            return [self._symbol]
        snapshot = self._universe_tracker.get_universe_on(self.now.date())
        return snapshot.tickers

    # ─── 账户面 ───

    def position(self, symbol: str) -> Position:
        return self._broker.get_position(symbol)

    @property
    def cash(self) -> float:
        return self._broker.cash

    @property
    def equity(self) -> float:
        # 现金 + 持仓市值（用当前 bar 价格估算）
        pos = self._broker.get_position(self._symbol)
        if self._cursor < len(self._df):
            current_price = float(self._df.iloc[self._cursor].get("close", 0.0))
            return self._broker.cash + pos.qty * current_price
        return self._broker.cash

    # ─── 执行面 ───

    def order(self, intent: OrderIntent) -> str:
        # 获取当前 bar 用于市价单撮合
        if self._cursor < len(self._df):
            row = self._df.iloc[self._cursor]
            bar = Bar(
                symbol=self._symbol,
                dt=self.now,
                open=float(row.get("open", 0.0)),
                high=float(row.get("high", 0.0)),
                low=float(row.get("low", 0.0)),
                close=float(row.get("close", 0.0)),
                volume=float(row.get("volume", 0.0)),
            )
            return self._broker.submit(intent, bar)
        return ""

    def cancel(self, order_id: str) -> bool:
        return self._broker.cancel(order_id)

    def open_orders(self) -> List[OrderUpdate]:
        pending = self._broker.get_open_orders()
        return [
            OrderUpdate(
                order_id=p.order_id,
                intent_tag=p.tag,
                status="PENDING",
            )
            for p in pending
        ]


class BacktestDriver:
    """回测驱动引擎

    主循环：
    1. 构造 RunManifest
    2. 数据装载（DataFrame）
    3. SimClock 逐 bar 推进：
       - 先撮合挂单/止损
       - 再驱动策略 on_bar
       - 分发成交回报
    4. 输出 BacktestResult
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._broker = SimBroker(
            config=SimBrokerConfig(
                commission_pct=config.commission_pct,
                slippage_pct=config.slippage_pct,
            ),
            initial_cash=config.initial_capital,
        )

    def run(
        self,
        strategy_cls: Type[Strategy],
        params: Dict[str, Any],
        df: pd.DataFrame,
        symbol: str,
        source_code: Optional[str] = None,
        pit_store: Optional["PointInTimeStore"] = None,
        universe_tracker: Optional["SurvivorshipBiasTracker"] = None,
    ) -> BacktestResult:
        """运行回测

        Args:
            strategy_cls: 策略类
            params: 策略参数
            df: K 线 DataFrame（index=DatetimeIndex，列含 open/high/low/close/volume）
            symbol: 标的代码
            source_code: 策略源码（用于计算 code_hash）
            pit_store: PIT 财务数据存储（可选）
            universe_tracker: 幸存者偏差追踪器（可选）

        Returns:
            BacktestResult
        """
        # 1. 准备数据
        df = self._prepare_dataframe(df)
        if len(df) < 10:
            raise ValueError("回测数据长度不足 (至少需要 10 根 K 线)")

        # 2. 构造 RunManifest（BT-02 可复现性绑定）
        code_hash = RunManifest.compute_code_hash(source_code or "")
        data_mode = self.config.data_mode or (
            "snapshot"
            if self.config.manifest_hash or (
                self.config.data_snapshot_id
                and self.config.data_snapshot_id not in ("live", "unbound", None)
            )
            else "unbound"
        )
        if self.config.data_snapshot_id == "live":
            data_mode = "live"
        manifest_hash = self.config.manifest_hash
        reproducible = (
            data_mode == "snapshot"
            and bool(code_hash)
            and bool(manifest_hash)
            and self.config.random_seed is not None
        )
        manifest = RunManifest(
            run_id=str(uuid.uuid4()),
            mode="backtest",
            code_hash=code_hash,
            params=params,
            data_snapshot_id=self.config.data_snapshot_id,
            manifest_hash=manifest_hash,
            random_seed=self.config.random_seed,
            data_mode=data_mode,  # type: ignore[arg-type]
            reproducible=reproducible,
        )

        # 3. 固定随机种子（同输入同输出）
        if self.config.random_seed is not None:
            np.random.seed(self.config.random_seed)
            import random as _random

            _random.seed(self.config.random_seed)

        # 4. 构造 Context
        clock = SimClock()
        ctx = BacktestContext(
            run_id=manifest.run_id,
            clock=clock,
            df=df,
            symbol=symbol,
            broker=self._broker,
            pit_store=pit_store,
            universe_tracker=universe_tracker,
        )

        # 5. 实例化策略
        strategy = strategy_cls(**params) if params else strategy_cls()

        # 6. 策略初始化
        strategy.on_init(ctx)

        # 7. 主循环
        equity_curve = []
        debug_logs = []
        benchmark_start = float(df.iloc[0].get("close", 1.0))

        for i in range(len(df)):
            ctx.set_cursor(i)
            row = df.iloc[i]
            bar_dt = df.index[i]
            if bar_dt.tzinfo is None:
                bar_dt = bar_dt.tz_localize(timezone.utc)

            # 推进时钟
            clock.set(bar_dt)

            # 构造当前 bar
            bar = Bar(
                symbol=symbol,
                dt=bar_dt,
                open=float(row.get("open", 0.0)),
                high=float(row.get("high", 0.0)),
                low=float(row.get("low", 0.0)),
                close=float(row.get("close", 0.0)),
                volume=float(row.get("volume", 0.0)),
            )

            # 先撮合挂单/止损
            self._broker.match_open_orders(bar)
            self._broker.check_stop_loss(bar)

            # 驱动策略
            strategy.on_bar(ctx, bar)

            # 分发成交回报
            self._broker.dispatch_fills(strategy, ctx)

            # 记录权益曲线
            current_equity = ctx.equity
            current_price = float(row.get("close", 0.0))
            date_str = str(bar_dt).split(" ")[0].split("T")[0]
            equity_curve.append({
                "date": date_str,
                "equity": round(current_equity, 2),
                "benchmark": round(self.config.initial_capital * (current_price / benchmark_start), 2),
                "price": round(current_price, 2),
            })

        # 8. 策略结束钩子
        strategy.on_stop(ctx)

        # 9. 计算指标
        metrics = self._compute_metrics(equity_curve, self._broker.state.trades)

        return BacktestResult(
            metrics=metrics,
            equity_curve=equity_curve,
            trades=self._broker.state.trades,
            debug_logs=debug_logs,
            manifest=manifest,
        )

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备 DataFrame：清理列名、处理重复列"""
        df = df.dropna().copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()].copy()
        # 统一列名为小写
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col.lower()] = df[col]
        return df

    def _compute_metrics(self, equity_curve: List[Dict], trades: List[Dict]) -> Dict[str, Any]:
        """计算回测指标"""
        if not equity_curve:
            return {
                "total_return": "0.00%",
                "sharpe_ratio": "0.00",
                "max_drawdown": "0.00%",
                "win_rate": "0.00%",
                "total_friction_cost": "$0.00",
            }

        equities = pd.Series([e["equity"] for e in equity_curve])
        initial = self.config.initial_capital
        final = equities.iloc[-1]
        total_return = (final - initial) / initial

        # 夏普比率
        daily_returns = equities.pct_change().dropna()
        if len(daily_returns) > 0 and daily_returns.std() != 0:
            sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        else:
            sharpe = 0.0

        # 最大回撤
        cummax = equities.cummax()
        drawdowns = (equities - cummax) / cummax
        max_dd = drawdowns.min() if len(drawdowns) > 0 else 0.0

        # 胜率
        sell_trades = [t for t in trades if t.get("action") == "SELL"]
        winning = [t for t in sell_trades if t.get("profit", 0) > 0]
        win_rate = len(winning) / len(sell_trades) if sell_trades else 0.0

        return {
            "engine": "🐢 BT-01b Event-Driven",
            "total_return": f"{total_return * 100:.2f}%",
            "sharpe_ratio": f"{sharpe:.2f}",
            "max_drawdown": f"{max_dd * 100:.2f}%",
            "win_rate": f"{win_rate * 100:.2f}%",
            "total_friction_cost": f"${self._broker.state.total_friction:,.2f}",
        }
