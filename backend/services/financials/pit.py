"""
FIN-04b · 回测侧 PIT 适配器（financial_facts → 回测引擎）
==========================================================

docs/28 §十红线：回测/因子只读 `value_as_reported` + `filed_as_reported <= as_of`。
旧内存 `datalake/financial_pit.PointInTimeStore` 与事实层双轨并存且从未接线
（`BacktestContext.financial` 传的 `PITQuery(field=...)` 本就不存在）——本模块替之。

设计：回测主循环同步逐 bar 推进，逐 bar 打 DB 不可行 → 回测启动时把该实体
全部 as_reported 事实一次性预载进内存（单票 10 年 ≈ 数千行），查询纯内存过滤。
即使重述已发生（filed_latest <= as_of），回测拿到的仍是首次披露值。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.financials_models import FinancialFact


@dataclass(frozen=True)
class PITPoint:
    """单条可回测事实（value 恒为首次披露值，冻结不改）。"""

    concept: str
    period_end: date
    filed_as_reported: date
    value: float
    restated: bool


class FinancialFactsPit:
    """预载式 PIT 视图：只读 value_as_reported，filed_as_reported <= as_of。

    `symbols` 为空表示单实体视图、接受任意 symbol；传入则做白名单校验
    （回测标的与预载实体不符时返回 None，不猜映射）。
    """

    def __init__(self, entity_id: str, points: Sequence[PITPoint], symbols: Sequence[str] = ()) -> None:
        self.entity_id = entity_id
        self.symbols = tuple(symbols)
        self._by_concept: dict[str, list[PITPoint]] = {}
        for p in points:
            self._by_concept.setdefault(p.concept, []).append(p)
        for pts in self._by_concept.values():
            pts.sort(key=lambda p: (p.period_end, p.filed_as_reported))

    @classmethod
    async def load(cls, session: AsyncSession, *, entity_id: str, symbols: Sequence[str] = ()) -> FinancialFactsPit:
        """预载实体的全部 as_reported 事实（回测启动时调用一次）。"""
        stmt = select(FinancialFact).where(
            FinancialFact.entity_id == entity_id,
            FinancialFact.value_as_reported.is_not(None),
        )
        rows = (await session.execute(stmt)).scalars().all()
        points = [
            PITPoint(
                concept=r.concept,
                period_end=r.period_end,
                filed_as_reported=r.filed_as_reported,
                value=float(r.value_as_reported),
                restated=r.filed_latest > r.filed_as_reported,
            )
            for r in rows
        ]
        return cls(entity_id, points, symbols)

    def latest_as_of(self, *, symbol: str, field: str, as_of: date) -> float | None:
        """as_of 时点已披露的最新一期首次披露值；未披露 / 不存在 → None（不补 0）。"""
        if self.symbols and symbol not in self.symbols:
            return None
        candidates = [p for p in self._by_concept.get(field, ()) if p.filed_as_reported <= as_of]
        if not candidates:
            return None
        return max(candidates, key=lambda p: (p.period_end, p.filed_as_reported)).value
