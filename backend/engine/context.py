"""
BT-01a · StrategyContext Protocol

策略与引擎之间的唯一 API 面。策略通过 ctx 访问：
- 元信息：now / mode / run_id
- 数据面：history() / quote() / financial() / universe()（全部隐式 as-of ctx.now）
- 账户面：position() / cash / equity
- 执行面：order() / cancel() / open_orders()
- 日志：log()

设计文档：docs/15. 回测实盘同构引擎设计.md §三.3
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Protocol, runtime_checkable

import pandas as pd

if TYPE_CHECKING:
    from .contracts import OrderIntent, OrderUpdate, Position, QuoteSnapshot


@runtime_checkable
class StrategyContext(Protocol):
    """策略上下文 Protocol——策略的唯一 API 面

    所有数据查询隐式 as-of ctx.now，架构级防前视。
    """

    # ─── 元信息 ───

    @property
    def now(self) -> datetime:
        """唯一合法时间源。回测=当前 bar 时间，实盘=墙钟"""
        ...

    @property
    def mode(self) -> Literal["backtest", "paper", "live"]:
        """运行模式"""
        ...

    @property
    def run_id(self) -> str:
        """本次运行的唯一 ID"""
        ...

    # ─── 数据面（全部隐式 as-of ctx.now，架构级防前视） ───

    def history(self, symbol: str, n: int, ktype: str = "K_DAY") -> pd.DataFrame:
        """获取截至 ctx.now 的历史 K 线（最近 n 根）

        返回 DataFrame 列：open/high/low/close/volume，index=DatetimeIndex
        """
        ...

    def quote(self, symbol: str) -> "QuoteSnapshot":
        """获取最新行情快照"""
        ...

    def financial(self, symbol: str, field: str) -> Optional[float]:
        """获取财务数据（Point-in-Time，as-of ctx.now）

        → financial_pit.get_financial_value(symbol, field, as_of=self.now)
        返回 None 表示数据未公布或不存在。
        """
        ...

    def universe(self) -> List[str]:
        """获取当前时点的标的池（幸存者偏差修正）

        → survivorship_bias.get_universe_for_backtest(check_date=self.now)
        """
        ...

    # ─── 账户面 ───

    def position(self, symbol: str) -> "Position":
        """获取指定标的持仓"""
        ...

    @property
    def cash(self) -> float:
        """可用现金"""
        ...

    @property
    def equity(self) -> float:
        """总权益（现金 + 持仓市值）"""
        ...

    # ─── 执行面 ───

    def order(self, intent: "OrderIntent") -> str:
        """提交订单意图，返回 order_id"""
        ...

    def cancel(self, order_id: str) -> bool:
        """取消订单，返回是否成功"""
        ...

    def open_orders(self) -> List["OrderUpdate"]:
        """获取当前挂单列表"""
        ...

    # ─── 日志 ───

    def log(self, event: str, **kw: Any) -> None:
        """结构化日志（structlog，实盘同时落 Bot 日志流）"""
        ...

    # ─── 订阅（on_init 阶段调用） ───

    def subscribe(self, symbols: List[str], warmup: int = 0) -> None:
        """声明订阅标的 + 预热窗口长度

        回测模式：仅用于标记（数据已预加载）
        实盘模式：向行情总线注册兴趣
        """
        ...


# ─────────────────────────────────────────────
# Context 基类实现（供 Driver 继承）
# ─────────────────────────────────────────────


class BaseContext:
    """StrategyContext 的公共基类实现

    Driver 继承此类并注入具体的数据/执行后端。
    """

    def __init__(
        self,
        mode: Literal["backtest", "paper", "live"],
        run_id: str,
        clock: Any,  # Clock Protocol
    ) -> None:
        self._mode = mode
        self._run_id = run_id
        self._clock = clock
        self._subscribed_symbols: List[str] = []
        self._warmup: int = 0
        self._logs: List[Dict[str, Any]] = []

    @property
    def now(self) -> datetime:
        return self._clock.now()

    @property
    def mode(self) -> Literal["backtest", "paper", "live"]:
        return self._mode

    @property
    def run_id(self) -> str:
        return self._run_id

    def subscribe(self, symbols: List[str], warmup: int = 0) -> None:
        self._subscribed_symbols = list(symbols)
        self._warmup = warmup

    def log(self, event: str, **kw: Any) -> None:
        entry = {"event": event, "ts": self.now.isoformat(), **kw}
        self._logs.append(entry)

    @property
    def logs(self) -> List[Dict[str, Any]]:
        """获取日志记录（测试/调试用）"""
        return self._logs.copy()
