"""
FIN-06: 同业引擎（services/financials/peers.py + service.get_peers）— 测试
==========================================================================

golden 全手算（docs/28 §5.2 + §六）：
  1. frames 帧矩阵：时点科目必须 I 后缀、流量 Q4/H1/9M 无帧（宁缺毋假）
  2. 截面分位与聚合可复算；样本 < 8 → 422 禁出分位结论
  3. Registry 只取 FRAMES；结构变化 / 限流语义化；不直连外网
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FinancialFact  # noqa: F401  注册 ORM
from backend.services.datasource import ErrorInfo, Result, ResultStatus
from backend.services.financials import peers, repository
from backend.services.financials.service import FinancialsError, FinancialsService, VersionedFact, resolve_entity_id

ENTITY = "US:CIK0000320193"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _fact(concept, statement, value, start, end, tag, entity_id=ENTITY):
    return VersionedFact(
        entity_id=entity_id,
        concept=concept,
        statement=statement,
        unit="USD",
        period_start=start,
        period_end=end,
        value_as_reported=float(value),
        value_latest=float(value),
        filed_as_reported=date(2026, 2, 1),
        filed_latest=date(2026, 2, 1),
        versions=1,
        restated=False,
        source="sec",
        source_tag=tag,
    )


def _revenue_seed(value=1200.0, tag="Revenues"):
    return [_fact("revenue", "income", value, date(2025, 1, 1), date(2025, 12, 31), tag)]


def _peer_fact(entity_id, value):
    """手工 peer 的 FY 事实（收入加权用）。"""
    return _fact("revenue", "income", value, date(2025, 1, 1), date(2025, 12, 31), "Revenues", entity_id=entity_id)


def _section(n=10, base=100.0):
    """frames 的 Result.data：本体 CIK320193 值最小 → 分位 = (0 + 0.5)/n * 100 手算可验。"""
    rows = []
    for i in range(n):
        rows.append({"cik": 320193 if i == 0 else 900000 + i, "val": base * (i + 1)})
    return {"taxonomy": "us-gaap", "tag": "Revenues", "data": rows}


# ─────────────────────────────────────────
#  1. 帧矩阵（docs/28 §3.3：用错后缀 SEC 404）
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "fy,fp,instant,expected",
    [
        (2025, "FY", False, "CY2025"),
        (2025, "Q1", False, "CY2025Q1"),
        (2025, "Q3", False, "CY2025Q3"),
        (2025, "Q4", False, None),  # Q4 流量帧不存在（用年度 CY）
        (2025, "H1", False, None),
        (2025, "9M", False, None),
        (2024, "FY", True, "CY2024Q4I"),  # 时点科目年末 = Q4I
        (2024, "Q3", True, "CY2024Q3I"),
        (2024, "9M", True, "CY2024Q3I"),  # 9M 末 = Q3 末
        (2024, "H1", True, "CY2024Q2I"),
        (2024, "H2", True, None),  # 未知/不可定位 → 拒绝
    ],
)
def test_frame_period_matrix(fy, fp, instant, expected):
    assert peers.frame_period(fy, fp, is_instant=instant) == expected


def test_parse_peer_set_normalizes_and_keeps_order():
    assert peers.parse_peer_set(" aapl , MSFT ,aapl,, ") == ["AAPL", "MSFT"]
    assert peers.parse_peer_set(None) == []


# ─────────────────────────────────────────
#  2. 截面解析 / 分位 / 聚合（手算）
# ─────────────────────────────────────────


def test_frames_cross_section_maps_cik_and_locks_structure():
    section = peers.frames_cross_section(_section(3))
    assert section == {
        "US:CIK0000320193": 100.0,
        "US:CIK0000900001": 200.0,
        "US:CIK0000900002": 300.0,
    }
    with pytest.raises(ValueError, match="结构变化"):
        peers.frames_cross_section({"units": {}})  # 缺 data 列表必须显式失败


def test_percentile_rank_hand_calculated():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert peers.percentile_rank(30.0, values) == pytest.approx(50.0)  # (2 + 0.5)/5
    assert peers.percentile_rank(50.0, values) == pytest.approx(90.0)  # (4 + 0.5)/5
    assert peers.percentile_rank(10.0, values) == pytest.approx(10.0)


def test_aggregate_quartiles_and_revenue_weighting():
    values = {f"E{i}": float(v) for i, v in enumerate([1, 2, 3, 4, 5])}
    out = peers.aggregate(values)
    assert out["count"] == 5 and out["median"] == 3.0 and out["p25"] == 2.0 and out["p75"] == 4.0

    weighted = peers.aggregate({"A": 2.0, "B": 4.0}, weights={"A": 100.0, "B": 300.0})
    assert weighted["revenue_weighted"] == pytest.approx((2 * 100 + 4 * 300) / 400)  # 3.5
    assert peers.aggregate({"A": 2.0}, weights={"B": 100.0}).get("revenue_weighted") is None  # 权重对不上不加权


def test_peer_view_sample_guard_and_missing_peers():
    section = peers.frames_cross_section(_section(10))
    # peers 模式：样本 = 本体 + 清单命中者；8 家 peer + 本体 = 9 ≥ 8 才出分位
    peers_ok = [f"US:CIK00009000{i:02d}" for i in range(1, 9)]  # 900001..900008 均在截面
    ok = peers.peer_view(section, entity_id=ENTITY, peer_ids=peers_ok)
    assert ok["sample_size"] == 9 and ok["percentile"] == pytest.approx(0.5 / 9 * 100)  # 本体最小
    assert ok["aggregates"]["median"] == pytest.approx(500.0)  # 100..900 的中位数
    assert ok["missing_peers"] == []

    # FIN-09：peer_rows 明细行按值升序（含本体，散点图数据支撑）
    assert [r["value"] for r in ok["peer_rows"]] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0]
    assert any(r["entity_id"] == ENTITY for r in ok["peer_rows"])

    # 清单里的 peer 截面缺席 → 如实报告，不悄悄缩样本
    partial = peers.peer_view(section, entity_id=ENTITY, peer_ids=[*peers_ok, "US:CIK0009999999"])
    assert partial["sample_size"] == 9 and partial["missing_peers"] == ["US:CIK0009999999"]

    # market 模式样本 6 家 < 8 → insufficient，禁出分位结论
    small = {k: v for k, v in list(section.items())[:6]}
    guarded = peers.peer_view(small, entity_id=ENTITY, peer_ids=[])
    assert guarded["insufficient"] is True and guarded["percentile"] is None

    with pytest.raises(ValueError, match="没有本体"):
        peers.peer_view(section, entity_id="US:CIK0000000001", peer_ids=[])


# ─────────────────────────────────────────
#  3. service.get_peers 编排
# ─────────────────────────────────────────


class FakeRegistry:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple[str, str, dict]] = []

    async def fetch(self, source_name, action, params):
        self.calls.append((source_name, action, params))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_get_peers_market_mode_uses_frames_cross_section(session):
    await repository.upsert_facts(session, _revenue_seed())
    registry = FakeRegistry(Result(status=ResultStatus.SUCCESS, data=_section(10), source="filings"))
    out = await FinancialsService(registry).get_peers(session, entity_id=ENTITY)

    assert registry.calls == [
        ("filings", "FRAMES", {"taxonomy": "us-gaap", "concept": "Revenues", "measure": "USD", "frame": "CY2025"})
    ]
    assert out["basis"] == "market" and out["frame"] == "CY2025"
    assert out["value"] == 100.0 and out["sample_size"] == 10
    assert out["percentile"] == pytest.approx(5.0)  # 本体值最小：(0+0.5)/10*100


async def test_get_peers_manual_peer_set_with_revenue_weights(session):
    """手工清单 + 收入加权：DB 只有 3 家事实，其余 peer 缺权重不参与加权（手算可验）。"""
    await repository.upsert_facts(session, _revenue_seed())
    peer_a, peer_b = "US:CIK0000900001", "US:CIK0000900002"
    await repository.upsert_facts(session, [_peer_fact(peer_a, 200.0), _peer_fact(peer_b, 300.0)])
    registry = FakeRegistry(Result(status=ResultStatus.SUCCESS, data=_section(10), source="filings"))
    peer_set = f"{peer_a}, {peer_b}, {','.join(f'US:CIK00009000{i:02d}' for i in range(3, 10))}"
    out = await FinancialsService(registry).get_peers(session, entity_id=ENTITY, peer_set=peer_set)

    assert out["basis"] == "peers" and out["sample_size"] == 10
    assert out["percentile"] == pytest.approx(0.5 / 10 * 100)
    # 加权只覆盖有权重的 3 家（100×1200 + 200×200 + 300×300）/ 1700
    assert out["aggregates"]["revenue_weighted"] == pytest.approx(
        (100 * 1200 + 200 * 200 + 300 * 300) / (1200 + 200 + 300)
    )


async def test_get_peers_sample_too_small_is_422(session):
    await repository.upsert_facts(session, _revenue_seed())
    registry = FakeRegistry(Result(status=ResultStatus.SUCCESS, data=_section(3), source="filings"))
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService(registry).get_peers(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_peer_sample_too_small", 422)
    assert "8" in exc.value.message


async def test_get_peers_error_mapping(session):
    await repository.upsert_facts(session, _revenue_seed())
    service = FinancialsService(
        FakeRegistry(
            Result(
                status=ResultStatus.RATE_LIMITED,
                error=ErrorInfo.rate_limited(message="SEC 429", retry_after=30),
                source="filings",
            )
        )
    )
    with pytest.raises(FinancialsError) as exc:
        await service.get_peers(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 429)

    broken = FinancialsService(FakeRegistry(Result(status=ResultStatus.SUCCESS, data={}, source="filings")))
    with pytest.raises(FinancialsError) as exc:
        await broken.get_peers(session, entity_id=ENTITY)  # frames 响应缺 data → 结构变化归 502
    assert exc.value.status_code == 502


async def test_get_peers_rejects_missing_fact_and_tag(session):
    service = FinancialsService(FakeRegistry(None))

    with pytest.raises(FinancialsError) as exc:
        await service.get_peers(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_no_xbrl_coverage", 404)

    await repository.upsert_facts(session, _revenue_seed(tag=""))  # 归一化丢标签的脏行
    with pytest.raises(FinancialsError) as exc:
        await service.get_peers(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_bad_request", 400)


def test_resolve_peer_entities_route_through_resolver():
    assert resolve_entity_id("aapl", symbol_to_cik={"AAPL": "0000320193"}) == ENTITY
    assert resolve_entity_id("700") == "HK:00700"
