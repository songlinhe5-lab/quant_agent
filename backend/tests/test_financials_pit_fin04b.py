"""
FIN-04b: 回测侧 PIT 切换（services/financials/pit.py）— 测试
=============================================================

红线（docs/28 §十）：回测只读 value_as_reported + filed_as_reported <= as_of。
golden 全手算：
  - FY2023 revenue 380_000，2024-02-02 首披
  - FY2024 revenue 400_000，2025-02-01 首披，2025-08-01 重述为 395_000
  - 回测在任何 as_of 拿到的都只能是首披值，重述值 395_000 永不可见
"""

from datetime import date, datetime, timezone

import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FilingRecord, FinancialFact  # noqa: F401  注册 ORM
from backend.engine.clock import SimClock
from backend.engine.drivers.backtest import BacktestConfig, BacktestContext, BacktestDriver
from backend.engine.drivers.sim_broker import SimBroker, SimBrokerConfig
from backend.engine.strategy import Strategy
from backend.services.financials.pit import FinancialFactsPit

ENTITY = "US:CIK0000320193"
SYMBOL = "AAPL"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _fact(concept, period_end, *, as_reported, filed, value_latest=None, filed_latest=None):
    restated = value_latest is not None and value_latest != as_reported
    return FinancialFact(
        entity_id=ENTITY,
        concept=concept,
        statement="income",
        period_start=None,
        period_start_key="",
        period_end=period_end,
        fiscal_year=period_end.year,
        fiscal_period="FY",
        unit="USD",
        value_as_reported=as_reported,
        value_latest=value_latest if value_latest is not None else as_reported,
        restated=restated,
        derived=False,
        filed_as_reported=filed,
        filed_latest=filed_latest or filed,
        source="sec",
        source_tag="Revenues",
    )


async def _seed(session):
    session.add_all(
        [
            _fact("revenue", date(2023, 12, 31), as_reported=380_000.0, filed=date(2024, 2, 2)),
            _fact(
                "revenue",
                date(2024, 12, 31),
                as_reported=400_000.0,
                filed=date(2025, 2, 1),
                value_latest=395_000.0,
                filed_latest=date(2025, 8, 1),
            ),
            _fact("net_income", date(2024, 12, 31), as_reported=100_000.0, filed=date(2025, 2, 1)),
        ]
    )
    await session.commit()


@pytest.fixture
async def pit(session):
    await _seed(session)
    return await FinancialFactsPit.load(session, entity_id=ENTITY, symbols=(SYMBOL,))


# ─────────────────────────────────────────
#  1. PIT 语义（防前视 golden）
# ─────────────────────────────────────────


async def test_load_reads_as_reported_only(session):
    await _seed(session)
    view = await FinancialFactsPit.load(session, entity_id=ENTITY)
    assert view.entity_id == ENTITY
    # as_of 晚于重述（2025-08-01），拿到的仍是首次披露值 400_000，重述值 395_000 不可见
    assert view.latest_as_of(symbol=SYMBOL, field="revenue", as_of=date(2026, 1, 1)) == 400_000.0


def test_look_ahead_is_blocked(pit):
    # FY2023 于 2024-02-02 披露：前一天不可知，当天起可见
    assert pit.latest_as_of(symbol=SYMBOL, field="revenue", as_of=date(2024, 2, 1)) is None
    assert pit.latest_as_of(symbol=SYMBOL, field="revenue", as_of=date(2024, 2, 2)) == 380_000.0


def test_picks_latest_disclosed_period(pit):
    # 2025-01-01：FY2024 未披露 → 只能给 FY2023
    assert pit.latest_as_of(symbol=SYMBOL, field="revenue", as_of=date(2025, 1, 1)) == 380_000.0
    # 2025-02-01 起：FY2024 可见
    assert pit.latest_as_of(symbol=SYMBOL, field="revenue", as_of=date(2025, 2, 1)) == 400_000.0


def test_restatement_value_never_leaks(pit):
    for as_of in (date(2025, 2, 1), date(2025, 8, 1), date(2030, 1, 1)):
        assert pit.latest_as_of(symbol=SYMBOL, field="revenue", as_of=as_of) == 400_000.0


def test_symbol_guard_and_unknown_concept(pit):
    assert pit.latest_as_of(symbol="MSFT", field="revenue", as_of=date(2026, 1, 1)) is None
    assert pit.latest_as_of(symbol=SYMBOL, field="no_such_concept", as_of=date(2026, 1, 1)) is None


async def test_no_symbol_whitelist_accepts_any(session):
    await _seed(session)
    view = await FinancialFactsPit.load(session, entity_id=ENTITY)
    assert view.latest_as_of(symbol="ANY", field="revenue", as_of=date(2024, 6, 1)) == 380_000.0


def test_restated_flag_marked(pit):
    by_period = {p.period_end: p for p in pit._by_concept["revenue"]}
    assert by_period[date(2024, 12, 31)].restated is True
    assert by_period[date(2023, 12, 31)].restated is False


# ─────────────────────────────────────────
#  2. 引擎集成（BacktestContext / BacktestDriver）
# ─────────────────────────────────────────


def _ctx(pit_view, at: datetime) -> BacktestContext:
    clock = SimClock()
    clock.set(at if at.tzinfo else at.replace(tzinfo=timezone.utc))
    return BacktestContext(
        run_id="t",
        clock=clock,
        df=pd.DataFrame({"close": [1.0]}),
        symbol=SYMBOL,
        broker=SimBroker(SimBrokerConfig(), initial_cash=100_000.0),
        pit=pit_view,
    )


def test_context_financial_is_pit(pit):
    assert _ctx(pit, datetime(2024, 1, 31)).financial(SYMBOL, "revenue") is None
    assert _ctx(pit, datetime(2024, 6, 1)).financial(SYMBOL, "revenue") == 380_000.0


def test_context_financial_without_pit_is_none():
    assert _ctx(None, datetime(2024, 6, 1)).financial(SYMBOL, "revenue") is None


def test_driver_run_smoke_with_pit(pit):
    """冒烟：旧实现传 pit 必在 PITQuery(field=) 处 TypeError，现在整链跑通。"""
    seen: list[tuple[str, float | None]] = []

    class FinReader(Strategy):
        def on_bar(self, ctx, bar):
            seen.append((str(ctx.now.date()), ctx.financial(bar.symbol, "revenue")))

    result = BacktestDriver(BacktestConfig()).run(FinReader, {}, _bars_df(), SYMBOL, pit=pit)

    assert result.manifest.mode == "backtest"
    disclosed = [d for d, v in seen if v is not None]
    assert disclosed and min(disclosed) >= "2024-02-02"  # 首披日前一律 None
    assert all(v == 380_000.0 for _, v in seen if v is not None)


def _bars_df() -> pd.DataFrame:
    idx = pd.date_range("2024-01-25", periods=12, freq="D")  # 跨过 2024-02-02 首披日
    prices = [100.0 + i for i in range(12)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1_000_000.0] * 12,
        },
        index=idx,
    )
