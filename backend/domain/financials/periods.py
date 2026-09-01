"""
FIN-02 · 期间推导（10-Q 的 YTD 陷阱）
=====================================

流量科目在 10-Q 里可能是**单季**也可能是**累计**，只能靠 `(start, end)` 跨度判定，
不能信 `fp` 标签（docs/28 §3.3）：

- 跨度 ≈ 91 天 → 单季，直接用
- 跨度 ≈ 182 / 273 天 → 累计：Q2 = H1 − Q1，Q3 = 9M − H1
- **Q4 永远是推导值**：Q4 = FY − 9M（EDGAR 无独立 Q4 申报），推导结果标 `derived=True`
- 存量科目（`Assets` / `StockholdersEquity`）是时点值，`start` 为 None
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

# 跨度分档：(标签, 中心天数, 容差)。季度 91±12 / 半年 182±12 / 前三季 273±15 / 全年 365±20
_DURATION_BANDS: tuple[tuple[str, int, int], ...] = (
    ("FY", 365, 20),
    ("9M", 273, 15),
    ("H1", 182, 12),
    ("Q", 91, 12),
)

CUMULATIVE_PERIODS = frozenset({"H1", "9M", "FY", "H2"})


class PeriodError(ValueError):
    """期间无法判定（不猜，调用方须显式处理）"""


def fiscal_year_of(end: date, fiscal_year_end_month: int = 12) -> int:
    """按财年结束月推导会计年度。

    12 月结束 → 自然年；非 12 月结束（如苹果 9 月）→ 落在结束月之后即算下一财年。
    """
    if not 1 <= fiscal_year_end_month <= 12:
        raise PeriodError(f"财年结束月非法: {fiscal_year_end_month}")
    if fiscal_year_end_month == 12:
        return end.year
    return end.year if end.month <= fiscal_year_end_month else end.year + 1


def _quarter_label(end: date, fiscal_year_end_month: int) -> str:
    """按期末相对财年起始的月数定位季度（1~3 月→Q1，…，结束月→FY）。"""
    offset = (end.month - fiscal_year_end_month) % 12
    if offset == 0:
        return "FY"
    return f"Q{(offset - 1) // 3 + 1}"


def days_between(start: date, end: date) -> int:
    """闭区间天数（EDGAR 的 start/end 均为含端点）。"""
    return (end - start).days + 1


class Period:
    """一个事实的会计期间"""

    __slots__ = ("start", "end", "fiscal_year", "fiscal_period", "days", "is_instant")

    def __init__(
        self,
        start: date | None,
        end: date,
        fiscal_year: int,
        fiscal_period: str,
        days: int,
        is_instant: bool,
    ) -> None:
        self.start = start
        self.end = end
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period
        self.days = days
        self.is_instant = is_instant

    @property
    def cumulative(self) -> bool:
        """该跨度是累计值（H1 / 9M / FY），需拆分后才能做单季比较"""
        return self.fiscal_period in CUMULATIVE_PERIODS

    @property
    def label(self) -> str:
        return period_label(self.fiscal_year, self.fiscal_period)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Period):
            return NotImplemented
        return (
            self.start == other.start
            and self.end == other.end
            and self.fiscal_year == other.fiscal_year
            and self.fiscal_period == other.fiscal_period
            and self.days == other.days
            and self.is_instant == other.is_instant
        )

    def __hash__(self) -> int:
        return hash((self.start, self.end, self.fiscal_year, self.fiscal_period, self.days, self.is_instant))

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"Period({self.label}, days={self.days}, start={self.start}, end={self.end})"


def period_label(fiscal_year: int, fiscal_period: str) -> str:
    """宽表列名：FY2024 / FY2024 Q1 / FY2024 H1"""
    if fiscal_period in {"FY", ""}:
        return f"FY{fiscal_year}"
    return f"FY{fiscal_year} {fiscal_period}"


def classify_period(
    start: date | None,
    end: date,
    fiscal_year_end_month: int = 12,
) -> Period:
    """由 `(start, end)` 判定期间。时点值 `start=None`。"""
    if end is None:
        raise PeriodError("period_end 缺失，拒绝猜测期间")
    fiscal_year = fiscal_year_of(end, fiscal_year_end_month)

    if start is None:
        return Period(None, end, fiscal_year, _quarter_label(end, fiscal_year_end_month), 0, True)

    days = days_between(start, end)
    quarter = _quarter_label(end, fiscal_year_end_month)
    for band, center, tol in _DURATION_BANDS:
        if abs(days - center) <= tol:
            if band == "Q":
                # 单季落在财年末：是 Q4 不是 FY（EDGAR 常见离散 Q4 申报，标成 FY 会污染年报快照）
                fiscal_period = "Q4" if quarter == "FY" else quarter
            else:
                fiscal_period = band
            return Period(start, end, fiscal_year, fiscal_period, days, False)

    # 跨度落在所有分档之外（如异常申报区间）：退回按月定位，累计与否按 100 天判定
    fiscal_period = quarter if days <= 100 else "FY"
    if fiscal_period == "FY" and days <= 100:
        fiscal_period = "Q4"  # 同上：短跨度撞上财年末仍是 Q4
    return Period(start, end, fiscal_year, fiscal_period, days, False)


class DerivedValue:
    """推导出的单季值（Q2/Q3/Q4 与 H2 必为推导，须标 derived）"""

    __slots__ = ("period", "start", "end", "value", "derived")

    def __init__(self, period: str, start: date | None, end: date, value: float, derived: bool) -> None:
        self.period = period
        self.start = start
        self.end = end
        self.value = value
        self.derived = derived

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"DerivedValue({self.period}, value={self.value}, derived={self.derived})"


def derive_quarters(
    cumulative: Mapping[str, tuple[date | None, date, float]],
) -> dict[str, DerivedValue]:
    """把累计口径拆成单季。

    入参：{期间标签: (start, end, value)}，标签 ∈ {Q1, H1, 9M, FY}
    出参：{Q1..Q4 / H2: DerivedValue}，缺输入即不产出（不猜）。
    """
    out: dict[str, DerivedValue] = {}

    q1 = cumulative.get("Q1")
    h1 = cumulative.get("H1")
    nine = cumulative.get("9M")
    fy = cumulative.get("FY")

    if q1:
        out["Q1"] = DerivedValue("Q1", q1[0], q1[1], float(q1[2]), False)
    if fy:
        out["FY"] = DerivedValue("FY", fy[0], fy[1], float(fy[2]), False)
    if h1:
        out["H1"] = DerivedValue("H1", h1[0], h1[1], float(h1[2]), False)

    if q1 and h1:
        out["Q2"] = DerivedValue("Q2", q1[1] + timedelta(days=1), h1[1], float(h1[2]) - float(q1[2]), True)
    if h1 and nine:
        out["Q3"] = DerivedValue("Q3", h1[1] + timedelta(days=1), nine[1], float(nine[2]) - float(h1[2]), True)
    if nine and fy:
        out["Q4"] = DerivedValue("Q4", nine[1] + timedelta(days=1), fy[1], float(fy[2]) - float(nine[2]), True)
    elif h1 and fy and not nine:
        # 没有 9M 申报时只能给下半年合计，不给 Q3/Q4（禁止把 H2 当 Q4）
        out["H2"] = DerivedValue("H2", h1[1] + timedelta(days=1), fy[1], float(fy[2]) - float(h1[2]), True)

    return out


def split_ytd(
    facts: Sequence[Any],
    fiscal_year_end_month: int = 12,
    *,
    include_source: bool = True,
) -> list[Any]:
    """把一批事实里的累计值补出单季值（Q4 必为推导）。

    入参元素需是带 `concept / period_start / period_end / value / derived` 的 dataclass
    （`mapper.NormalizedFact` 即是）。推导结果一律 `derived=True`，前端须标浅色角标。
    """
    groups: dict[tuple[str, int], list[Any]] = {}
    for fact in facts:
        period = classify_period(fact.period_start, fact.period_end, fiscal_year_end_month)
        if period.is_instant:
            continue  # 存量科目不拆
        groups.setdefault((fact.concept, period.fiscal_year), []).append((period, fact))

    derived: list[Any] = []
    for (_concept, _fy), items in groups.items():
        cumulative: dict[str, tuple[date | None, date, float]] = {}
        for period, fact in items:
            if period.fiscal_period in {"Q1", "H1", "9M", "FY"}:
                cumulative.setdefault(period.fiscal_period, (period.start, period.end, fact.value))
        quarters = derive_quarters(cumulative)
        source = {period.fiscal_period: fact for period, fact in items}
        for label, value in quarters.items():
            if not value.derived:
                continue
            base = source.get("FY") or source.get("9M") or source.get("H1") or source.get("Q1")
            if base is None:
                continue
            derived.append(
                replace(
                    base,
                    period_start=value.start,
                    period_end=value.end,
                    value=value.value,
                    derived=True,
                )
            )

    return list(facts) + derived if include_source else derived
