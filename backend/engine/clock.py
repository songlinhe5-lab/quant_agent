"""
BT-01a · 时钟抽象（Clock Protocol + 双实现）

策略/Context 内禁止出现 datetime.now() 直调，一切时间经 Clock——同构的根基。

- SimClock：回测模式，由 Driver 逐 bar set()，策略侧只读
- WallClock：实盘/纸面模式，datetime.now(UTC)

设计文档：docs/15. 回测实盘同构引擎设计.md §四.4
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """时钟协议——策略获取时间的唯一入口"""

    def now(self) -> datetime:
        """返回当前时间（timezone-aware UTC）"""
        ...


class SimClock:
    """模拟时钟：回测模式，由 Driver 逐 bar set()

    初始时间为 epoch，Driver 在每个 bar 开始前 set(bar.dt)。
    """

    def __init__(self) -> None:
        self._current: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def set(self, dt: datetime) -> None:
        """由 Driver 调用，推进到指定 bar 时间"""
        if dt.tzinfo is None:
            raise ValueError("SimClock.set requires timezone-aware datetime")
        if dt < self._current:
            raise ValueError(f"SimClock cannot go backwards: {dt} < {self._current}")
        self._current = dt

    def reset(self) -> None:
        """重置到 epoch（新一轮回测）"""
        self._current = datetime(1970, 1, 1, tzinfo=timezone.utc)


class WallClock:
    """真实墙钟：实盘/纸面模式，直接返回 datetime.now(UTC)"""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)
