"""
FIN-05: 分析引擎接线（views.build_analytics_view + service.get_analytics）— 测试
================================================================================

域层引擎的手算 golden 在 test_financials_analytics_fin05.py，这里只验证**接线**：
  1. FY 快照装配正确（季度值不得混进 DuPont/评分模型；TTM 单独走拆季）
  2. 缺年报 → 404（不返回空壳 200）；实体无事实 → 404
  3. as_of PIT 透传；market_cap 只透传不自估

数值沿用域层测试的同一套手算基准（revenue 1200 / NI 132 / equity 500 …）。
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FinancialFact  # noqa: F401  注册 ORM
from backend.services.financials import repository
from backend.services.financials.service import FinancialsError, FinancialsService, VersionedFact  # noqa: F401

ENTITY = "US:CIK0000320193"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _fact(concept, statement, value, start, end, filed_year):
    return VersionedFact(
        entity_id=ENTITY,
        concept=concept,
        statement=statement,
        unit="USD",
        period_start=start,
        period_end=end,
        value_as_reported=float(value),
        value_latest=float(value),
        filed_as_reported=date(filed_year, 2, 1),
        filed_latest=date(filed_year, 2, 1),
        versions=1,
        restated=False,
        source="sec",
        source_tag=concept,
    )


_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}


def _annual(value_by_concept, year, filed_year):
    statement_of = {
        "revenue": "income",
        "net_income": "income",
        "pretax_income": "income",
        "operating_income": "income",
        "gross_profit": "income",
        "total_assets": "balance",
        "stockholders_equity": "balance",
        "total_liabilities": "balance",
        "total_current_assets": "balance",
        "total_current_liabilities": "balance",
        "retained_earnings": "balance",
        "accounts_receivable": "balance",
        "depreciation_amortization": "cash",
        "ppe_net": "balance",
        "cfo": "cash",
        "capex": "cash",
        "shares_diluted": "per_share",
    }
    return [
        _fact(concept, statement_of[concept], value, date(year, 1, 1), date(year, 12, 31), filed_year)
        for concept, value in value_by_concept.items()
    ]


FY2024 = {
    "revenue": 1000.0,
    "net_income": 100.0,
    "pretax_income": 120.0,
    "operating_income": 150.0,
    "gross_profit": 250.0,
    "total_assets": 800.0,
    "stockholders_equity": 400.0,
    "total_liabilities": 420.0,
    "total_current_assets": 350.0,
    "total_current_liabilities": 200.0,
    "retained_earnings": 100.0,
    "accounts_receivable": 100.0,
    "depreciation_amortization": 55.0,
    "ppe_net": 380.0,
    "cfo": 120.0,
    "capex": 50.0,
    "shares_diluted": 1020.0,
}
FY2025 = {
    "revenue": 1200.0,
    "net_income": 132.0,
    "pretax_income": 150.0,
    "operating_income": 180.0,
    "gross_profit": 360.0,
    "total_assets": 1000.0,
    "stockholders_equity": 500.0,
    "total_liabilities": 500.0,
    "total_current_assets": 400.0,
    "total_current_liabilities": 200.0,
    "retained_earnings": 150.0,
    "accounts_receivable": 120.0,
    "depreciation_amortization": 60.0,
    "ppe_net": 400.0,
    "cfo": 150.0,
    "capex": 60.0,
    "shares_diluted": 1000.0,
}


def _quarter(fy, q, value):
    end_m, end_d = _QUARTER_END[q]
    return _fact(
        "revenue",
        "income",
        value,
        date(fy, _QUARTER_START_MONTH[q], 1),
        date(fy, end_m, end_d),
        fy + 1,
    )


async def _seed(session):
    await repository.upsert_facts(session, _annual(FY2024, 2024, 2025) + _annual(FY2025, 2025, 2026))
    # 单季收入（FY2024 全年 + FY2025 Q1）：手算 → Q4 TTM=460，FY2025 Q1 TTM=500
    await repository.upsert_facts(
        session,
        [
            _quarter(2024, 1, 100),
            _quarter(2024, 2, 110),
            _quarter(2024, 3, 120),
            _quarter(2024, 4, 130),
            _quarter(2025, 1, 140),
        ],
    )


async def test_get_analytics_assembles_engine_view(session):
    await _seed(session)
    out = await FinancialsService().get_analytics(session, entity_id=ENTITY)

    assert out["entity_id"] == ENTITY and out["latest_period"] == "FY2025"

    # DuPont 只认年报：FY2024（期末基数兜底）+ FY2025（均值资产）；ROE = 132/500（手算）
    assert len(out["dupont"]) == 2
    dup = next(d for d in out["dupont"] if d["period"] == "FY2025")
    assert dup["roe"] == pytest.approx(0.264) and dup["asset_base"] == "average"

    # 现金流质量（FY2025 最新一期，capex 归一为正 → FCF = 150−60 = 90）
    assert out["cash_flow_quality"]["fcf"] == pytest.approx(90.0)
    assert out["cash_flow_quality"]["cfo_to_net_income"] == pytest.approx(150 / 132)

    # 三分都在，且给分项而非黑箱总分
    assert out["piotroski"]["max_score"] == 9 and len(out["piotroski"]["items"]) == 9
    assert out["altman_z"]["thresholds"] == {"safe": 2.99, "grey": 1.81}
    assert out["beneish_m"]["threshold"] == -1.78

    # TTM：拆季 + 四季滚动（域层手算基准）
    assert out["ttm"]["revenue"] == [
        {"label": "FY2024 Q4 TTM", "value": 460.0},
        {"label": "FY2025 Q1 TTM", "value": 500.0},
    ]


async def test_get_analytics_market_cap_passthrough_never_estimated(session):
    await _seed(session)
    service = FinancialsService()

    no_cap = await service.get_analytics(session, entity_id=ENTITY)
    assert no_cap["altman_z"]["z"] is None and "market_cap" in no_cap["altman_z"]["missing"]

    with_cap = await service.get_analytics(session, entity_id=ENTITY, market_cap=3000.0)
    assert with_cap["altman_z"]["z"] == pytest.approx(5.844) and with_cap["altman_z"]["zone"] == "safe"


async def test_get_analytics_pit_as_of_filters_unfiled_facts(session):
    await _seed(session)
    # FY2025 于 2026-02-01 披露：在此之前只看得见 FY2024
    out = await FinancialsService().get_analytics(session, entity_id=ENTITY, as_of=date(2025, 6, 30))
    assert out["latest_period"] == "FY2024"
    assert [d["period"] for d in out["dupont"]] == ["FY2024"]  # 缺 FY2023 年报 → 期末基数兜底
    assert out["dupont"][0]["asset_base"] == "ending"


async def test_get_analytics_rejects_empty_and_quarter_only_entities(session):
    service = FinancialsService()

    with pytest.raises(FinancialsError) as exc:
        await service.get_analytics(session, entity_id="US:CIK0009999999")
    assert (exc.value.code, exc.value.status_code) == ("fin_entity_not_found", 404)

    # 只有单季、没有年报 → 拒绝出分析（季度口径须年化，容易误导）
    await repository.upsert_facts(session, [_quarter(2025, 1, 140.0)])
    with pytest.raises(FinancialsError) as exc:
        await service.get_analytics(session, entity_id=ENTITY)
    assert exc.value.code == "fin_entity_not_found" and "年报" in exc.value.message
