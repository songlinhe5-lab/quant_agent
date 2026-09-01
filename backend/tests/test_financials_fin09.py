"""
FIN-09: 数据运维（coverage 审计 / 批量回填 / 当日快照刷新）— 测试
================================================================

golden 全手算（docs/28 §九验收：缺失期显式列出，禁止补零；覆盖率口径可复现）。
单测不打真实外网 / 不写真实快照根目录。
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import backend.services.datalake.paths as datalake_paths
from backend.core.database import Base
from backend.core.financials_models import FinancialFact
from backend.services.financials import jobs
from backend.services.financials.coverage import audit_coverage
from backend.services.financials.service import FinancialsError, FinancialsService

ENTITY = "US:CIK0000320193"
TODAY = date(2026, 9, 1)


# ─────────────────────────────────────────
#  1. coverage 纯函数（手算）
# ─────────────────────────────────────────


class F:
    """轻量 fact 桩（audit_coverage 只 getattr 这几个字段）。"""

    def __init__(self, concept, fiscal_year, fiscal_period="FY", value=100.0):
        self.concept = concept
        self.fiscal_year = fiscal_year
        self.fiscal_period = fiscal_period
        self.value_latest = value
        self.value_as_reported = value


def test_audit_coverage_golden_missing_listed_not_zeroed():
    # 窗口 2024~2026（today=2026-09-01, years=3）：
    # revenue: FY2024/FY2025 有值、FY2026 缺 → missing [2026]，coverage 2/3
    # net_income: 只有 FY2025 → missing [2024, 2026]，1/3
    # total_assets / total_equity / cfo: 全缺 → 0/3
    facts = [
        F("revenue", 2024),
        F("revenue", 2025),
        F("net_income", 2025),
        # 季度行不参与年度审计
        F("revenue", 2026, fiscal_period="Q1"),
        # 窗口外的年份不算
        F("revenue", 2020),
    ]
    out = audit_coverage(facts, today=TODAY, years=3)

    assert out["window"] == {"start_year": 2024, "end_year": 2026, "years": 3}
    by_concept = {c["concept"]: c for c in out["concepts"]}
    assert by_concept["revenue"]["missing_years"] == [2026]
    assert by_concept["revenue"]["coverage_pct"] == round(2 / 3, 4)
    assert by_concept["net_income"]["missing_years"] == [2024, 2026]
    assert by_concept["total_assets"]["coverage_pct"] == 0.0
    # 总口径 3/15 = 0.2，可手算复现
    assert out["coverage_pct"] == 0.2
    # 缺失显式列出（不给补零，给清单）
    assert {"concept": "revenue", "years": [2026]} in out["missing"]
    assert {"concept": "cfo", "years": [2024, 2025, 2026]} in out["missing"]


def test_audit_coverage_empty_facts_is_zero_not_error():
    out = audit_coverage([], today=TODAY, years=3)
    assert out["coverage_pct"] == 0.0
    assert len(out["missing"]) == 5  # 五个核心科目全缺，如实列出


# ─────────────────────────────────────────
#  2. service 层（sqlite 内存库）
# ─────────────────────────────────────────


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _fact(concept, fiscal_year, statement="income", value=100.0, entity_id=ENTITY):
    return FinancialFact(
        entity_id=entity_id,
        concept=concept,
        statement=statement,
        period_start=None,
        period_start_key="",
        period_end=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        unit="USD",
        value_as_reported=value,
        value_latest=value,
        restated=False,
        derived=False,
        filed_as_reported=date(fiscal_year + 1, 2, 1),
        filed_latest=date(fiscal_year + 1, 2, 1),
        source="sec",
        source_tag="Revenues",
    )


@pytest.mark.asyncio
async def test_get_coverage_via_service(session):
    session.add(_fact("revenue", 2026))
    await session.flush()
    out = await FinancialsService(None).get_coverage(session, entity_id=ENTITY, years=3)
    assert out["entity_id"] == ENTITY
    assert out["coverage_pct"] == round(1 / 15, 4)


@pytest.mark.asyncio
async def test_backfill_batch_limits_and_scheduling(session, monkeypatch):
    svc = FinancialsService(None)

    with pytest.raises(FinancialsError) as ei:
        svc.backfill_batch(lambda: None, entities=[])
    assert ei.value.code == "fin_bad_request"

    with pytest.raises(FinancialsError) as ei:
        svc.backfill_batch(lambda: None, entities=[f"E{i}" for i in range(51)])
    assert ei.value.code == "fin_bad_request"

    # 正常路径：monkeypatch 掉 schedule_backfill，验证逐实体调度不真跑采集
    monkeypatch.setattr(
        FinancialsService, "schedule_backfill", lambda self, sf, *, entity_id, source="sec": f"job-{entity_id}"
    )
    out = svc.backfill_batch(lambda: None, entities=["aapl", "msft"])
    assert out == [
        {"entity_id": "aapl", "job_id": "job-aapl"},
        {"entity_id": "msft", "job_id": "job-msft"},
    ]


@pytest.mark.asyncio
async def test_refresh_daily_snapshot_writes_parquet(session, tmp_path, monkeypatch):
    monkeypatch.setattr(datalake_paths, "SNAPSHOTS_ROOT", tmp_path)
    for row in (_fact("revenue", 2025), _fact("net_income", 2025), _fact("total_assets", 2025, "balance")):
        session.add(row)
    await session.flush()

    # 第二个实体也应有宽表（refresh 面向全部已回填实体，不挑食）
    session.add(_fact("revenue", 2025, entity_id="US:CIK0000320194"))
    await session.flush()

    out = await FinancialsService(None).refresh_daily_snapshot(session)
    assert out["entities"] == 2
    assert out["snapshot_id"].startswith("snap_financials_")
    table = tmp_path / out["snapshot_id"] / "financials" / "US_CIK0000320193" / "income.parquet"
    assert table.exists(), "当日快照必须真实落盘（docs/19 引用链）"
    assert (tmp_path / out["snapshot_id"] / "financials" / "US_CIK0000320194").exists()


@pytest.mark.asyncio
async def test_job_registry_records_batch_scheduling(session, monkeypatch):
    jobs.reset_jobs()
    svc = FinancialsService(None)
    monkeypatch.setattr(
        FinancialsService,
        "schedule_backfill",
        lambda self, sf, *, entity_id, source="sec": jobs.create_job(entity_id=entity_id, source=source),
    )
    out = svc.backfill_batch(lambda: None, entities=["aapl"])
    assert jobs.get_job(out[0]["job_id"])["entity_id"] == "aapl"
