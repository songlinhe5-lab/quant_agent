"""
FIN-04: 回填任务登记簿 + CPU 段（jobs）— 单元测试
================================================

验证:
  1. 任务状态机：pending → running → success/failed（进程内登记簿）
  2. `submit` 把重计算卸载到 `run_cpu_bound`，且卸载对象是**模块级纯函数**（可 pickle）
  3. `transform_payload`：归一化 + 累计拆分（Q4 推导）+ 三表勾稽标注 + 双时间轴折叠
  4. 勾稽失败只标注、不丢数，且只涂在参与该校验的报表上

单测不打真实进程池（ARCH-07 已覆盖），也不打外网/DB。
"""

import pickle
from datetime import date

import pytest

from backend.domain.financials.mapper import VersionedFact
from backend.services.financials import jobs

ENTITY = "US:CIK0000320193"


@pytest.fixture(autouse=True)
def _clean_jobs():
    jobs.reset_jobs()
    yield
    jobs.reset_jobs()


def _row(val, start=None, end="2025-12-31", filed="2026-02-01", accn="accn-1", form="10-K"):
    row = {"val": val, "end": end, "filed": filed, "accn": accn, "form": form, "fy": 2025, "fp": "FY"}
    if start:
        row["start"] = start
    return row


def _sec_payload():
    """SEC companyfacts 结构：facts[taxonomy][tag].units[unit] -> [row...]"""
    return {
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            _row(200, "2025-01-01"),
                            _row(150, "2025-01-01", end="2025-09-30", accn="accn-2", form="10-Q"),
                            _row(50, "2025-01-01", end="2025-03-31", accn="accn-3", form="10-Q"),
                        ]
                    }
                },
                "CostOfRevenue": {"units": {"USD": [_row(120, "2025-01-01")]}},
                "GrossProfit": {"units": {"USD": [_row(70, "2025-01-01")]}},  # 应为 80 → 毛利勾稽失败
                "Assets": {"units": {"USD": [_row(500)]}},  # 时点值：无 start
                "Liabilities": {"units": {"USD": [_row(400)]}},
                "StockholdersEquity": {"units": {"USD": [_row(50)]}},  # 500 ≠ 450 → 平衡式失败
                "CashDivsTotal": {"units": {"USD": [_row(1)]}},  # 未映射标签
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_row(1)]}}},
        },
    }


def _run(payload=None, **params):
    return jobs.transform_payload(
        payload if payload is not None else _sec_payload(),
        {"entity_id": ENTITY, "source": "sec", "taxonomy": "us-gaap", **params},
    )


def _by_concept(result, concept):
    return [f for f in result["facts"] if f["concept"] == concept]


# ─────────────────────────────────────────
#  1. 任务登记簿
# ─────────────────────────────────────────


def test_create_and_update_job_transitions_status():
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    job = jobs.get_job(job_id)
    assert job["status"] == "pending" and job["progress"] == 0
    assert job["created_at"].endswith("Z")

    jobs.update_job(job_id, status="running", progress=40)
    jobs.update_job(job_id, status="success", progress=100, result={"facts_written": 7})
    done = jobs.get_job(job_id)
    assert done["status"] == "success" and done["result"]["facts_written"] == 7
    assert done["error"] is None


def test_get_job_returns_copy_and_list_orders_newest_first():
    first = jobs.create_job(entity_id="A", source="sec")
    second = jobs.create_job(entity_id="B", source="sec")
    snapshot = jobs.get_job(first)
    snapshot["status"] = "tampered"
    assert jobs.get_job(first)["status"] == "pending"  # 外部改不动登记簿
    assert [j["job_id"] for j in jobs.list_jobs()][0] == second

    assert jobs.get_job("nope") is None
    with pytest.raises(KeyError):
        jobs.update_job("nope", status="failed")


async def test_submit_offloads_picklable_pure_function(monkeypatch):
    seen = {}

    async def fake_run_cpu_bound(func, *args, **kwargs):
        seen["func"] = func
        return {"facts": [], "stats": {}, "integrity": {}}

    monkeypatch.setattr("backend.core.cpu_pool.run_cpu_bound", fake_run_cpu_bound)
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    result = await jobs.submit(job_id, {"facts": {}}, {"entity_id": ENTITY})

    assert result == {"facts": [], "stats": {}, "integrity": {}}
    assert seen["func"] is jobs.transform_payload
    assert pickle.dumps(jobs.transform_payload)  # 进程池的硬前提：模块级可 pickle
    job = jobs.get_job(job_id)
    assert job["status"] == "running" and job["progress"] == 80  # 卸载前后推进进度


# ─────────────────────────────────────────
#  2. CPU 段：归一化 + 拆分 + 勾稽
# ─────────────────────────────────────────


def test_transform_normalizes_and_counts_unmapped():
    result = _run()
    concepts = {f["concept"] for f in result["facts"]}
    assert {"revenue", "cost_of_revenue", "gross_profit", "total_assets"} <= concepts
    assert "dei" not in str(result["facts"])  # 非 us-gaap 分类不进事实层
    assert result["stats"]["unmapped"]["us-gaap:CashDivsTotal"] == 1  # 未命中映射只计数，不猜值


def test_quarter_derivation_from_cumulative_periods():
    revenues = {(f["period_start"], f["period_end"]): f for f in _by_concept(_run(), "revenue")}
    assert date(2025, 10, 1) in [r for r, _ in revenues.keys()]  # Q4 被补出
    q4 = revenues[(date(2025, 10, 1), date(2025, 12, 31))]
    assert q4["value_latest"] == 50.0 and q4["derived"] is True  # FY − 9M
    fy = revenues[(date(2025, 1, 1), date(2025, 12, 31))]
    assert fy["derived"] is False


def test_check_failures_are_attributed_to_the_right_statement():
    result = _run()
    balance = _by_concept(result, "total_assets")[0]
    income_base = _by_concept(result, "revenue")

    assert balance["check_failed"] == ["balance_identity"]
    gross = _by_concept(result, "gross_profit")[0]
    assert gross["check_failed"] == ["gross_profit"]
    # 资产平衡失败不得涂到利润表；毛利失败不得涂到资产负债表
    assert all("balance_identity" not in f["check_failed"] for f in income_base)
    assert all("gross_profit" not in f["check_failed"] for f in _by_concept(result, "total_liabilities"))


def test_derived_quarters_do_not_pollute_the_check_bucket():
    """毛利在 FY 口径下平（200−120=80）；若被推导的 Q4（50）盖进同桶，就会误判失败"""
    payload = _sec_payload()
    payload["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"] = [_row(80, "2025-01-01")]
    result = _run(payload)

    assert all("gross_profit" not in f["check_failed"] for f in _by_concept(result, "revenue"))
    q4 = next(f for f in _by_concept(result, "revenue") if f["derived"])
    assert q4["check_failed"] == []  # 推导值不参与勾稽


def test_failed_rows_are_kept_not_dropped():
    """docs/28 §3.4：勾稽失败只标注，数字照常入库（禁止静默丢数）"""
    result = _run()
    total = len(result["facts"])
    assert total >= 7
    assert result["integrity"]["failed_periods"][date(2025, 12, 31).isoformat()] == [
        "balance_identity",
        "gross_profit",
    ]
    assert result["integrity"]["checked_periods"] >= 3


def test_facts_round_trip_into_versioned_fact():
    """CPU 段产出的 dict 必须能被 `VersionedFact(**item)` 直接吃下（service 依赖此约定）"""
    for item in _run()["facts"]:
        fact = VersionedFact(**item)
        assert fact.entity_id == ENTITY
        assert fact.filed_as_reported <= fact.filed_latest


def test_collapsed_versions_track_restatement():
    payload = _sec_payload()
    units = payload["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"]
    units.append(_row(80, "2025-01-01", filed="2027-02-01", accn="accn-9", form="10-K/A"))
    gross = _by_concept(_run(payload), "gross_profit")[0]

    assert gross["versions"] == 2
    assert gross["value_as_reported"] == 70.0 and gross["value_latest"] == 80.0
    assert gross["restated"] is True
    assert gross["filed_as_reported"] == date(2026, 2, 1) and gross["filed_latest"] == date(2027, 2, 1)


def test_row_style_source_goes_through_from_rows():
    tushare_rows = {
        "rows": [
            {"tag": "total_revenue", "value": 100, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-04-30"}
        ]
    }
    result = jobs.transform_payload(
        tushare_rows,
        {
            "entity_id": "CN:600519",
            "source": "tushare",
            "taxonomy": "tushare",
            "tag_field": "tag",
            "value_field": "value",
            "start_field": "start",
            "end_field": "end",
            "filed_field": "filed",
            "unit": "CNY",
        },
    )
    fact = result["facts"][0]
    assert fact["concept"] == "revenue" and fact["source"] == "tushare" and fact["unit"] == "CNY"
    assert fact["source_tag"] == "total_revenue"
    assert fact["check_failed"] == []  # 凑不齐三项 → 该期直接跳过校验


def test_empty_payload_yields_no_facts():
    result = _run({"facts": {}})
    assert result["facts"] == [] and result["integrity"]["checked_periods"] == 0


# ─────────────────────────────────────────
#  FIN-10 · PG 快照（financial_jobs 表）
# ─────────────────────────────────────────


@pytest.fixture
async def pg_jobs(monkeypatch):
    """sqlite 内存库充当 PG；monkeypatch 还原 _session_factory，不污染其他测试。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from backend.core import financials_models  # noqa: F401  注册 ORM（含 FinancialsJob）
    from backend.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(jobs, "_session_factory", factory)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_persist_then_recover_after_restart(pg_jobs):
    """create+persist → 清内存（模拟重启）→ get_job_any 从 PG 恢复终态。"""
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await jobs.update_job_persisted(job_id, status="failed", error="boom")

    jobs.reset_jobs()  # 模拟进程重启：内存全丢
    assert jobs.get_job(job_id) is None

    recovered = await jobs.get_job_any(job_id)
    assert recovered is not None
    assert recovered["entity_id"] == ENTITY
    assert recovered["status"] == "failed" and recovered["error"] == "boom"
    assert recovered["result"] == {}  # PG 里为 NULL → 读侧归一为空 dict


@pytest.mark.asyncio
async def test_get_job_memory_takes_precedence(pg_jobs):
    """内存命中直接返回，不打 PG（热路径零 DB 开销）。"""
    job_id = jobs.create_job(entity_id=ENTITY, source="tushare")
    assert (await jobs.get_job_any(job_id))["source"] == "tushare"


@pytest.mark.asyncio
async def test_get_job_any_unknown_id_returns_none(pg_jobs):
    assert await jobs.get_job_any("finbf_nope") is None


@pytest.mark.asyncio
async def test_mark_stale_failed_converges_nonterminal(pg_jobs):
    """重启收敛：pending/running → failed；终态不动。"""
    ok_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await jobs.update_job_persisted(ok_id, status="success", progress=100)

    stale_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await jobs.update_job_persisted(stale_id, status="running", progress=40)

    n = await jobs.mark_stale_failed()
    assert n >= 1  # 只碰非终态

    async with pg_jobs() as session:
        ok = await session.get(jobs.FinancialsJob, ok_id)
        stale = await session.get(jobs.FinancialsJob, stale_id)
    assert ok.status == "success" and ok.error is None  # 终态不被误伤
    assert stale.status == "failed" and stale.error == "interrupted by restart"


@pytest.mark.asyncio
async def test_persist_noop_without_configure():
    """未接线（工厂 None）→ persist/get_job_any 静默 no-op，纯内存行为不回归。"""
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await jobs.persist(job_id)  # 不抛
    assert (await jobs.get_job_any(job_id))["entity_id"] == ENTITY  # 内存命中
    jobs.reset_jobs()
    assert await jobs.get_job_any(job_id) is None  # 内存 miss 且无工厂 → 不查库，返回 None
