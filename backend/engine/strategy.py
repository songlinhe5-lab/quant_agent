"""
BT-01a · Strategy 抽象基类

用户策略的唯一基类。策略只依赖 Strategy + StrategyContext，
永远不知道自己跑在回测还是实盘。

生命周期：on_init → on_bar (循环) → on_order_update (可选) → on_stop

设计文档：docs/15. 回测实盘同构引擎设计.md §三.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional

import pandas as pd

if TYPE_CHECKING:
    from .contracts import Bar, OrderUpdate
    from .context import StrategyContext


class Strategy(ABC):
    """用户策略唯一基类

    禁止在策略内 import 任何 service / redis / futu。
    策略的所有能力通过 ctx: StrategyContext 获取。
    """

    # 策略参数（构造时注入，网格寻优的变量面）
    params: ClassVar[Dict[str, Any]] = {}

    def on_init(self, ctx: "StrategyContext") -> None:
        """初始化钩子：声明订阅标的、预热窗口长度等

        默认空实现，策略可选覆盖。
        示例：ctx.subscribe(["HK.00700"], warmup=60)
        """
        pass

    @abstractmethod
    def on_bar(self, ctx: "StrategyContext", bar: "Bar") -> None:
        """逐 bar 驱动——唯一必须实现的方法

        回测与实盘语义完全一致：
        - 回测：Driver 逐根历史 bar 调用
        - 实盘：LiveDriver 在 bar 闭合时调用

        策略通过 ctx.order(OrderIntent(...)) 下单。
        """
        ...

    def on_order_update(self, ctx: "StrategyContext", update: "OrderUpdate") -> None:
        """订单回报回调（可选）

        成交/拒单/部分成交时由 Driver 调用。
        """
        pass

    def on_stop(self, ctx: "StrategyContext") -> None:
        """清理钩子（可选）

        实盘停止 / 回测结束时调用。
        """
        pass

    # ─── QUANT-01 矢量化快路径（可选声明） ───

    @classmethod
    def signals(cls, df: pd.DataFrame, params: Dict[str, Any]) -> Optional[pd.Series]:
        """纯函数：完整 OHLCV → 信号列（1/-1/0）

        返回 None 表示本策略不支持矢量化，只能走事件驱动。
        实现者必须保证与 on_bar 语义等价（由同构校验器验证）。

        Args:
            df: 完整 OHLCV DataFrame（index=DatetimeIndex）
            params: 策略参数字典

        Returns:
            pd.Series of int (1=买入, -1=卖出, 0=持有), 或 None
        """
        return None

    @classmethod
    def is_vectorizable(cls) -> bool:
        """本策略是否支持矢量化快路径"""
        return cls.signals.__func__ is not Strategy.signals.__func__
