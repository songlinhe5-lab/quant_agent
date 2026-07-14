"""
BT-01a · 同构策略引擎（Isomorphic Strategy Engine）

公开 API：
- Strategy: 用户策略基类
- StrategyContext: 策略上下文 Protocol
- Bar / QuoteSnapshot / OrderIntent / OrderUpdate / Position: 数据契约
- RunManifest: 运行指纹
- Clock / SimClock / WallClock: 时钟抽象

设计文档：docs/15. 回测实盘同构引擎设计.md
"""

from .clock import Clock, SimClock, WallClock
from .context import BaseContext, StrategyContext
from .contracts import (
    Bar,
    OrderIntent,
    OrderUpdate,
    Position,
    QuoteSnapshot,
    RunManifest,
)
from .strategy import Strategy

__all__ = [
    # 策略基类
    "Strategy",
    # 上下文
    "StrategyContext",
    "BaseContext",
    # 数据契约
    "Bar",
    "QuoteSnapshot",
    "OrderIntent",
    "OrderUpdate",
    "Position",
    "RunManifest",
    # 时钟
    "Clock",
    "SimClock",
    "WallClock",
]
