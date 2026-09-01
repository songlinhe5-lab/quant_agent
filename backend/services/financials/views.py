"""
FIN-04 · 报表视图装配（纯函数，无 IO）
======================================

把 FIN-03 仓储读出的**长表事实**装配成前端要的**多期宽表**（docs/28 §四 `StatementView`）。

铁律在此落地：
  - 口径可见：`basis` 必须写进响应，用户得知道在看 as_reported 还是 latest
  - 缺失不补零：拿不到的科目期间一律 `None`，前端显式留白
  - 推导值可辨：`derived` 逐格透出，前端标浅色角标
  - 勾稽失败不静默：`integrity` 汇总每期的 `check_failed`
  - 来源可溯：`source_mix` 统计 sec / futu / tushare 各占几行
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from backend.core.financials_models import FilingRecord, FinancialFact
from backend.domain.financials import analytics
from backend.domain.financials.mapper import load_concept_map
from backend.domain.financials.periods import period_label

from .repository import BASIS_AS_REPORTED, BASIS_LATEST, pit_value

# common-size 基线：利润/现金流表以收入为基，资产负债表以总资产为基
BASE_CONCEPT = {"income": "revenue", "cash": "revenue", "balance": "total_assets"}


def _pick(fact: FinancialFact, as_of: date | None, basis: str) -> float | None:
    """PIT 优先：带 as_of 时按可知晓性取值，否则按口径取值。"""
    if as_of is not None:
        return pit_value(fact, as_of, basis)
    return fact.value_as_reported if basis == BASIS_AS_REPORTED else fact.value_latest


def _yoy(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return current / previous - 1


def build_statement_view(
    facts: Sequence[FinancialFact],
    *,
    entity_id: str,
    statement: str,
    basis: str = BASIS_LATEST,
    as_of: date | None = None,
) -> dict[str, Any]:
    """长表 → 多期宽表。行 = 标准科目，列 = 期间（财年老→新）。

    流量科目的累计口径（H1 / 9M / FY）在入参里已是稳定行，这里只按
    `fiscal_year` + `fiscal_period` 打列名，不再二次拆分（拆季在归一化阶段做）。
    """
    rows: dict[str, dict[str, Any]] = {}
    period_keys: dict[str, tuple[int, str]] = {}  # 列名 -> (财年, 排序序)
    source_mix: dict[str, int] = {}
    units: set[str] = set()

    for fact in facts:
        value = _pick(fact, as_of, basis)
        col = period_label(fact.fiscal_year, fact.fiscal_period)
        period_keys.setdefault(col, (fact.fiscal_year, fact.fiscal_period))
        source_mix[fact.source] = source_mix.get(fact.source, 0) + 1
        if fact.unit:
            units.add(fact.unit)

        # 同 (科目, 期间) 多版本冲突：保留最近一次披露（filed_latest 更大者）。
        # 仲裁键必须是 (科目, 列)——只按列比会把同列的其他科目当旧版本静默丢掉。
        row = rows.setdefault(
            fact.concept,
            {"concept": fact.concept, "label": _label(fact.concept), "values": {}, "flags": {}},
        )
        filed = fact.filed_latest or date.min
        previous = row["flags"].get(col)
        if previous is not None and filed <= previous["filed"]:
            continue
        row["values"][col] = value
        row["flags"][col] = {
            "filed": filed,
            "derived": fact.derived,
            "restated": fact.restated,
            "check_failed": list(fact.check_failed or []),
        }

    periods = sorted(period_keys, key=lambda c: (period_keys[c][0], _period_rank(period_keys[c][1])))
    base_values = {col: (rows.get(BASE_CONCEPT.get(statement, ""), {}).get("values") or {}).get(col) for col in periods}

    payload: list[dict[str, Any]] = []
    for concept in sorted(rows):
        row = rows[concept]
        values = [row["values"].get(col) for col in periods]
        flags = [row["flags"].get(col) for col in periods]
        payload.append(
            {
                "concept": concept,
                "label": row["label"],
                "values": values,
                "common_size": _common_size(values, base_values, periods),
                "yoy": _series_yoy(values, periods),
                "derived": [bool((f or {}).get("derived")) for f in flags],
                "restated": [bool((f or {}).get("restated")) for f in flags],
                "check_failed": [sorted((f or {}).get("check_failed") or []) for f in flags],
            }
        )

    return {
        "entity_id": entity_id,
        "statement": statement,
        "periods": periods,
        "rows": payload,
        "basis": basis,
        "as_of": as_of.isoformat() if as_of else None,
        "currency": _currency(units),
        "source_mix": source_mix,
        "integrity": summarize_integrity(facts, periods, period_keys),
    }


def _period_rank(fiscal_period: str) -> int:
    return {"Q1": 1, "Q2": 2, "H1": 3, "Q3": 4, "9M": 5, "Q4": 6, "H2": 6, "FY": 7}.get(fiscal_period, 0)


def _currency(units: Iterable[str]) -> str:
    """报表币种：取金额单位（份额类 units 不当作币种）。多币种并存时置空并让前端标源。"""
    money = {u for u in units if u in _CURRENCY_CODES}
    return next(iter(money)) if len(money) == 1 else ""


_CURRENCY_CODES = frozenset({"USD", "HKD", "CNY", "EUR", "GBP", "JPY"})


def _label(concept: str) -> str:
    """展示名一律取自 concept_map（数据即配置，禁在服务层写死文案）。"""
    concept_def = load_concept_map().concepts.get(concept)
    return concept_def.label if concept_def else concept


def _common_size(
    values: Sequence[float | None],
    base_values: Mapping[str, float | None],
    periods: Sequence[str],
) -> list[float | None]:
    """占基线（收入 / 总资产）的百分比；基线缺失或为 0 → None（不猜、不补零）。"""
    out: list[float | None] = []
    for value, col in zip(values, periods):
        base = base_values.get(col)
        if value is None or not base:
            out.append(None)
        else:
            out.append(value / abs(base) * 100)
    return out


def _series_yoy(values: Sequence[float | None], periods: Sequence[str]) -> list[float | None]:
    """同财年同跨度的上一年对比：FY2025 对 FY2024，Q1 只对 Q1，绝不拿季度比年度。"""
    index = {col: i for i, col in enumerate(periods)}
    out: list[float | None] = []
    for i, col in enumerate(periods):
        year, _, rest = col.partition(" ")
        prev_col = f"FY{int(year[2:]) - 1} {rest}".strip() if year.startswith("FY") else None
        j = index.get(prev_col) if prev_col else None
        out.append(_yoy(values[i], values[j]) if j is not None else None)
    return out


def summarize_integrity(
    facts: Sequence[FinancialFact],
    periods: Sequence[str],
    _period_keys: Mapping[str, tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """勾稽摘要：失败期次与失败项必须透出，禁止只报「一切正常」。"""
    failed: dict[str, list[str]] = {}
    for fact in facts:
        for name in fact.check_failed or []:
            col = period_label(fact.fiscal_year, fact.fiscal_period)
            bucket = failed.setdefault(col, [])
            if name not in bucket:
                bucket.append(name)
    checked = {c for c in failed}
    return {
        "failed_periods": sorted(checked, key=lambda c: periods.index(c) if c in periods else 0),
        "failures": failed,
        "total_facts": len(facts),
        "derived_facts": sum(1 for f in facts if f.derived),
        "restated_facts": sum(1 for f in facts if f.restated),
    }


def build_fact_view(facts: Iterable[FinancialFact]) -> list[dict[str, Any]]:
    """科目级明细（含双时间轴全部溯源字段）。"""
    return [fact.to_dict() for fact in facts]


def build_restatement_view(facts: Sequence[FinancialFact]) -> list[dict[str, Any]]:
    """重述 diff：首次披露 vs 最新，绝对差与相对差都给（相对差不猜，分母为 0 时置 None）。"""
    out: list[dict[str, Any]] = []
    for fact in facts:
        delta = fact.value_latest - fact.value_as_reported
        ratio = delta / abs(fact.value_as_reported) if fact.value_as_reported else None
        out.append(
            {
                **fact.to_dict(),
                "label": _label(fact.concept),
                "delta": delta,
                "delta_pct": ratio,
            }
        )
    return out


def build_filing_view(filings: Iterable[FilingRecord]) -> list[dict[str, Any]]:
    return [f.to_dict() for f in filings]


# ── FIN-05 · 分析引擎装配（docs/28 §5.1）──

# DuPont / 质量三分需要的全部科目（引擎侧缺失不补 0，只列 missing）
ANALYTICS_CONCEPTS = (
    "revenue",
    "net_income",
    "pretax_income",
    "operating_income",
    "gross_profit",
    "total_assets",
    "stockholders_equity",
    "total_liabilities",
    "total_current_assets",
    "total_current_liabilities",
    "long_term_debt",
    "retained_earnings",
    "accounts_receivable",
    "selling_general_admin",
    "depreciation_amortization",
    "ppe_net",
    "cfo",
    "capex",
    "shares_diluted",
)
TTM_CONCEPTS = ("revenue", "net_income", "cfo")  # 财年错位公司的同比基准


def build_analytics_view(
    facts: Sequence[FinancialFact], *, as_of: date | None = None, market_cap: float | None = None
) -> dict[str, Any]:
    """报表事实 → 分析视图。DuPont/评分模型只认**年报**快照（季度须年化，容易误导）；
    TTM 部分按科目拆季再四季滚动。无 FY 快照返回空 dict，由调用方降 404。"""
    snapshots: dict[str, dict[str, float]] = {}
    quarterly: dict[str, dict[int, list[analytics.Point]]] = {}
    for fact in facts:
        if fact.concept not in ANALYTICS_CONCEPTS:
            continue
        value = pit_value(fact, as_of=as_of)
        if value is None:
            continue
        if fact.fiscal_period == "FY":
            snapshots.setdefault(period_label(fact.fiscal_year, fact.fiscal_period), {})[fact.concept] = value
        elif fact.concept in TTM_CONCEPTS:
            per_fy = quarterly.setdefault(fact.concept, {})
            per_fy.setdefault(fact.fiscal_year, []).append(
                analytics.Point(
                    label=period_label(fact.fiscal_year, fact.fiscal_period),
                    fiscal_year=fact.fiscal_year,
                    fiscal_period=fact.fiscal_period,
                    value=value,
                )
            )
    if not snapshots:
        return {}

    ttm: dict[str, list[dict[str, Any]]] = {}
    for concept, per_fy in quarterly.items():
        quarters = [q for fy in sorted(per_fy) for q in analytics.quarterly_values(per_fy[fy])]
        ttm[concept] = [{"label": p.label, "value": p.value} for p in analytics.ttm_series(quarters)]

    latest_label = max(snapshots, key=lambda label: int(label[2:]))
    latest = snapshots[latest_label]
    prior = snapshots.get(f"FY{int(latest_label[2:]) - 1}", {})
    return {
        "latest_period": latest_label,
        "dupont": analytics.dupont_series(snapshots),
        "cash_flow_quality": analytics.cash_flow_quality(latest, prior_assets=prior.get("total_assets")),
        "piotroski": analytics.piotroski_f(latest, prior),
        "altman_z": analytics.altman_z(latest, market_cap=market_cap),
        "beneish_m": analytics.beneish_m(latest, prior),
        "ttm": ttm,
    }
