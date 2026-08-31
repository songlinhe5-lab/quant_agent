"""
FIN-03 · 财报事实层仓储（双时间轴 + PIT 查询）
=============================================

只做**存储与读取**，不做采集、不做编排（采集在 FIN-01、编排在 FIN-04）。

两条时间轴的落地规则（docs/28 §3.2）:
  - `filed_as_reported` / `value_as_reported`：首次披露，写入后**冻结**（回测与因子只读这条）
  - `filed_latest` / `value_latest`：最新一次涉及该键的申报（含重述）
  - 两者不等 → `restated=True`

PIT 取值（`pit_value`）:
  - as_of < filed_as_reported → 尚未公布，SQL 层已过滤掉（防前视偏差）
  - filed_as_reported <= as_of < filed_latest → 只可能知道首次披露值
  - as_of >= filed_latest → 已知最新值
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.financials_models import FilingRecord, FinancialFact
from backend.domain.financials.mapper import VersionedFact
from backend.domain.financials.periods import classify_period

logger = structlog.get_logger(__name__)

BASIS_AS_REPORTED = "as_reported"
BASIS_LATEST = "latest"


def period_start_key(period_start: date | None) -> str:
    """唯一键用的非空列：PG 的 NULL 互不相等，时点值统一写空串"""
    return period_start.isoformat() if period_start else ""


def pit_value(fact: FinancialFact, as_of: date | None = None, basis: str = BASIS_LATEST) -> float | None:
    """按 PIT 语义取值；as_of 早于首次披露返回 None（该数字当时不可知）。"""
    if as_of is not None and as_of < fact.filed_as_reported:
        return None
    if as_of is not None and as_of < fact.filed_latest:
        return fact.value_as_reported  # 重述尚未发生，市场只知道首次披露值
    return fact.value_as_reported if basis == BASIS_AS_REPORTED else fact.value_latest


async def upsert_facts(
    session: AsyncSession,
    facts: Sequence[VersionedFact],
    *,
    fiscal_year_end_month: int = 12,
) -> int:
    """写入（或推进）一批事实，按唯一键幂等。返回写入行数。"""
    written = 0
    for fact in facts:
        period = classify_period(fact.period_start, fact.period_end, fiscal_year_end_month)
        key = (
            FinancialFact.entity_id == fact.entity_id,
            FinancialFact.concept == fact.concept,
            FinancialFact.period_start_key == period_start_key(fact.period_start),
            FinancialFact.period_end == fact.period_end,
            FinancialFact.unit == fact.unit,
        )
        row = (await session.execute(select(FinancialFact).where(*key))).scalars().first()

        if row is None:
            session.add(
                FinancialFact(
                    entity_id=fact.entity_id,
                    concept=fact.concept,
                    statement=fact.statement,
                    period_start=fact.period_start,
                    period_start_key=period_start_key(fact.period_start),
                    period_end=fact.period_end,
                    fiscal_year=period.fiscal_year,
                    fiscal_period=period.fiscal_period,
                    unit=fact.unit,
                    value_as_reported=fact.value_as_reported,
                    value_latest=fact.value_latest,
                    restated=fact.restated,
                    derived=fact.derived,
                    filed_as_reported=fact.filed_as_reported or fact.filed_latest,
                    filed_latest=fact.filed_latest or fact.filed_as_reported,
                    accession_no=fact.accession_no,
                    source=fact.source,
                    source_tag=fact.source_tag,
                )
            )
            written += 1
            continue

        # 已有键：as_reported 冻结，只推进 latest
        if fact.filed_as_reported and fact.filed_as_reported < row.filed_as_reported:
            row.filed_as_reported = fact.filed_as_reported
            row.value_as_reported = fact.value_as_reported
        if fact.filed_latest and fact.filed_latest >= row.filed_latest:
            row.filed_latest = fact.filed_latest
            row.value_latest = fact.value_latest
            row.accession_no = fact.accession_no or row.accession_no
        row.restated = row.value_as_reported != row.value_latest
        row.source_tag = fact.source_tag or row.source_tag
        written += 1

    await session.commit()
    logger.info("财报事实写入完成", rows=written)
    return written


async def get_facts(
    session: AsyncSession,
    *,
    entity_id: str,
    concept: str | None = None,
    statement: str | None = None,
    as_of: date | None = None,
    include_derived: bool = True,
    limit: int = 500,
) -> list[FinancialFact]:
    """读取事实；传 `as_of` 即 PIT 查询（只返回当时已披露的）。"""
    stmt = select(FinancialFact).where(FinancialFact.entity_id == entity_id)
    if concept:
        stmt = stmt.where(FinancialFact.concept == concept)
    if statement:
        stmt = stmt.where(FinancialFact.statement == statement)
    if as_of is not None:
        stmt = stmt.where(FinancialFact.filed_as_reported <= as_of)  # 前视偏差拦截
    if not include_derived:
        stmt = stmt.where(FinancialFact.derived.is_(False))
    stmt = stmt.order_by(FinancialFact.concept, FinancialFact.period_end).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_restatements(session: AsyncSession, *, entity_id: str, limit: int = 200) -> list[FinancialFact]:
    """重述清单：首次披露值与最新值不相等的科目"""
    stmt = (
        select(FinancialFact)
        .where(FinancialFact.entity_id == entity_id, FinancialFact.restated.is_(True))
        .order_by(FinancialFact.period_end.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def upsert_filings(session: AsyncSession, records: Iterable[dict[str, Any]]) -> int:
    """申报归档入库，按 (entity_id, accession_no) 幂等。"""
    written = 0
    for rec in records:
        key = (
            FilingRecord.entity_id == rec["entity_id"],
            FilingRecord.accession_no == rec["accession_no"],
        )
        row = (await session.execute(select(FilingRecord).where(*key))).scalars().first()
        if row is None:
            session.add(FilingRecord(**rec))
        else:
            for field in ("form_type", "fiscal_year", "filed_at", "doc_url", "lang", "rag_indexed"):
                if field in rec:
                    setattr(row, field, rec[field])
        written += 1
    await session.commit()
    return written


async def get_filings(session: AsyncSession, *, entity_id: str, limit: int = 100) -> list[FilingRecord]:
    stmt = (
        select(FilingRecord)
        .where(FilingRecord.entity_id == entity_id)
        .order_by(FilingRecord.filed_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
