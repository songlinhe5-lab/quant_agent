"""
FIN-03: 双时间轴存储（repository）— 单元测试
=============================================

验证:
  1. 幂等写入：唯一键 = entity + concept + period_start_key + period_end + unit
  2. as_reported 冻结、latest 推进、restated 自动判定
  3. PIT 查询：只返回 as_of 前已披露的数字（防前视偏差）
  4. 重述清单与申报归档索引

用 SQLite(aiosqlite) 内存库跑，不打真实 PG/Redis/外网。
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.core.database import Base
from backend.core.financials_models import FilingRecord, FinancialFact  # noqa: F401  注册 ORM
from backend.domain.financials.mapper import VersionedFact
from backend.services.financials import repository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _vf(
    concept: str = "revenue",
    *,
    start: date | None = date(2025, 1, 1),
    end: date = date(2025, 12, 31),
    as_reported: float = 100.0,
    latest: float | None = None,
    filed_first: date = date(2026, 2, 1),
    filed_last: date | None = None,
    statement: str = "income",
    unit: str = "USD",
    entity_id: str = "US:CIK0000320193",
    derived: bool = False,
) -> VersionedFact:
    latest = as_reported if latest is None else latest
    filed_last = filed_last or filed_first
    return VersionedFact(
        entity_id=entity_id,
        concept=concept,
        statement=statement,
        unit=unit,
        period_start=start,
        period_end=end,
        value_as_reported=as_reported,
        value_latest=latest,
        filed_as_reported=filed_first,
        filed_latest=filed_last,
        versions=1,
        restated=as_reported != latest,
        source="sec",
        source_tag="Revenues",
        accession_no="accn-1",
        derived=derived,
    )


# ─────────────────────────────────────────
#  1. 幂等写入与双时间轴
# ─────────────────────────────────────────


async def test_upsert_inserts_new_fact_with_period_metadata(session):
    await repository.upsert_facts(session, [_vf()])
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193"))[0]

    assert row.concept == "revenue"
    assert row.fiscal_year == 2025 and row.fiscal_period == "FY"
    assert row.period_start_key == "2025-01-01"
    assert row.value_as_reported == 100.0 and row.value_latest == 100.0
    assert row.filed_as_reported == date(2026, 2, 1)
    assert row.restated is False


async def test_upsert_freezes_as_reported_on_restatement(session):
    await repository.upsert_facts(session, [_vf(filed_first=date(2026, 2, 1))])
    await repository.upsert_facts(
        session,
        [_vf(as_reported=100.0, latest=118.0, filed_first=date(2026, 2, 1), filed_last=date(2027, 2, 1))],
    )
    rows = await repository.get_facts(session, entity_id="US:CIK0000320193")

    assert len(rows) == 1  # 同一唯一键不新增行
    assert rows[0].value_as_reported == 100.0  # 首次披露值冻结
    assert rows[0].value_latest == 118.0
    assert rows[0].filed_as_reported == date(2026, 2, 1)
    assert rows[0].filed_latest == date(2027, 2, 1)
    assert rows[0].restated is True


async def test_upsert_backfills_as_reported_when_earlier_filing_arrives(session):
    """晚到的早期申报（回填历史）要把 as_reported 往前推"""
    await repository.upsert_facts(session, [_vf(as_reported=118.0, filed_first=date(2027, 2, 1))])
    await repository.upsert_facts(
        session,
        [_vf(as_reported=100.0, latest=118.0, filed_first=date(2026, 2, 1), filed_last=date(2027, 2, 1))],
    )
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193"))[0]

    assert row.value_as_reported == 100.0
    assert row.filed_as_reported == date(2026, 2, 1)
    assert row.restated is True


async def test_upsert_does_not_flag_restate_when_value_unchanged(session):
    await repository.upsert_facts(session, [_vf(filed_first=date(2026, 2, 1))])
    await repository.upsert_facts(session, [_vf(filed_first=date(2026, 2, 1), filed_last=date(2027, 2, 1))])
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193"))[0]
    assert row.restated is False
    assert row.filed_latest == date(2027, 2, 1)


async def test_distinct_periods_stay_separate_rows(session):
    """禁按 fy 去重：Q1 与 FY 共用 fy 标签，必须各占一行"""
    await repository.upsert_facts(
        session,
        [
            _vf(end=date(2025, 3, 31), as_reported=40.0),
            _vf(end=date(2025, 12, 31), as_reported=200.0),
        ],
    )
    rows = await repository.get_facts(session, entity_id="US:CIK0000320193")
    assert len(rows) == 2
    assert [r.period_end for r in rows] == [date(2025, 3, 31), date(2025, 12, 31)]


async def test_instant_fact_uses_empty_period_start_key(session):
    await repository.upsert_facts(
        session, [_vf(concept="total_assets", start=None, statement="balance", as_reported=359.0)]
    )
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193"))[0]
    assert row.period_start is None
    assert row.period_start_key == ""
    assert row.statement == "balance"


async def test_fiscal_year_end_month_is_respected(session):
    """苹果 9 月财年：2025-09-27 属 FY2025"""
    await repository.upsert_facts(
        session,
        [_vf(start=date(2024, 9, 29), end=date(2025, 9, 27))],
        fiscal_year_end_month=9,
    )
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193"))[0]
    assert row.fiscal_year == 2025 and row.fiscal_period == "FY"


# ─────────────────────────────────────────
#  2. PIT 查询
# ─────────────────────────────────────────


async def test_pit_excludes_unpublished_facts(session):
    await repository.upsert_facts(session, [_vf(filed_first=date(2026, 2, 1))])
    assert await repository.get_facts(session, entity_id="US:CIK0000320193", as_of=date(2026, 1, 15)) == []
    assert len(await repository.get_facts(session, entity_id="US:CIK0000320193", as_of=date(2026, 3, 1))) == 1


async def test_pit_value_before_restatement_returns_as_reported(session):
    await repository.upsert_facts(
        session,
        [_vf(as_reported=100.0, latest=118.0, filed_first=date(2026, 2, 1), filed_last=date(2027, 2, 1))],
    )
    row = (await repository.get_facts(session, entity_id="US:CIK0000320193", as_of=date(2026, 6, 1)))[0]

    assert repository.pit_value(row, date(2026, 6, 1)) == 100.0  # 重述未发生
    assert repository.pit_value(row, date(2028, 1, 1)) == 118.0  # 已知最新
    assert repository.pit_value(row, date(2026, 1, 1)) is None  # 当时不可知
    assert repository.pit_value(row, None, basis=repository.BASIS_AS_REPORTED) == 100.0


async def test_get_facts_filters_by_concept_statement_and_derived(session):
    await repository.upsert_facts(
        session,
        [
            _vf(concept="revenue"),
            _vf(concept="net_income", as_reported=20.0),
            _vf(concept="cfo", statement="cash", as_reported=30.0),
            _vf(concept="revenue", start=date(2025, 10, 1), as_reported=50.0, derived=True),
        ],
    )
    all_rows = await repository.get_facts(session, entity_id="US:CIK0000320193")
    assert len(all_rows) == 4  # Q4 推导值与 FY 期间不同，独立成行（禁按 fy 合并）

    revenue = await repository.get_facts(session, entity_id="US:CIK0000320193", concept="revenue")
    assert len(revenue) == 2
    cash = await repository.get_facts(session, entity_id="US:CIK0000320193", statement="cash")
    assert [r.concept for r in cash] == ["cfo"]
    no_derived = await repository.get_facts(
        session, entity_id="US:CIK0000320193", concept="revenue", include_derived=False
    )
    assert len(no_derived) == 1 and no_derived[0].derived is False


async def test_get_restatements_returns_only_restated_rows(session):
    await repository.upsert_facts(
        session,
        [
            _vf(
                concept="revenue",
                as_reported=100.0,
                latest=118.0,
                filed_first=date(2026, 2, 1),
                filed_last=date(2027, 2, 1),
            ),
            _vf(concept="net_income", as_reported=20.0),
        ],
    )
    restated = await repository.get_restatements(session, entity_id="US:CIK0000320193")
    assert [r.concept for r in restated] == ["revenue"]


# ─────────────────────────────────────────
#  3. 申报归档索引
# ─────────────────────────────────────────


async def test_upsert_filings_is_idempotent_and_updatable(session):
    rec = {
        "entity_id": "US:CIK0000320193",
        "form_type": "10-K",
        "fiscal_year": 2025,
        "filed_at": date(2025, 10, 31),
        "accession_no": "0000320193-25-000123",
        "doc_url": "https://www.sec.gov/Archives/edgar/...",
        "lang": "en",
    }
    assert await repository.upsert_filings(session, [rec]) == 1
    assert await repository.upsert_filings(session, [{**rec, "rag_indexed": True}]) == 1

    rows = await repository.get_filings(session, entity_id="US:CIK0000320193")
    assert len(rows) == 1
    assert rows[0].rag_indexed is True


async def test_get_filings_orders_by_filed_at_desc(session):
    base = {
        "entity_id": "HK:00700",
        "form_type": "年報",
        "doc_url": "https://www.hkexnews.hk/...",
        "lang": "zh",
    }
    await repository.upsert_filings(
        session,
        [
            {**base, "fiscal_year": 2024, "filed_at": date(2025, 3, 22), "accession_no": "a1"},
            {**base, "fiscal_year": 2025, "filed_at": date(2026, 3, 22), "accession_no": "a2"},
        ],
    )
    rows = await repository.get_filings(session, entity_id="HK:00700")
    assert [r.filed_at for r in rows] == [date(2026, 3, 22), date(2025, 3, 22)]


async def test_period_start_key_helper():
    assert repository.period_start_key(date(2025, 1, 1)) == "2025-01-01"
    assert repository.period_start_key(None) == ""
