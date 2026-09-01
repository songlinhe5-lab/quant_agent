"""
FIN-04: 财报编排服务（service）— 单元测试
=========================================

覆盖 docs/28 §二服务层与 §六错误码：
  1. 实体解析（ticker / CIK / 港A代码）与 PIT 日期入参：解析不了就显式失败
  2. 回填流水线：一手 payload → 归一（进程池）→ PG 双时间轴 → 申报索引 → Parquet 宽表
  3. 降级语义：限流 429 / 源不可用 502 / 无 XBRL 覆盖 404 / 未接入源 501
  4. 申报归档是旁路：拉不到只记警告，不阻断数字层入库
  5. 后台任务自持会话（请求返回后会话关闭也不影响回填收尾）
  6. 读路径校验与装配

Registry 用假对象，进程池就地执行，Parquet 写 tmp_path —— 不打真实外网/PG/进程池。
"""

import asyncio
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FilingRecord, FinancialFact  # noqa: F401  注册 ORM
from backend.services.datasource import ErrorInfo, Result, ResultStatus
from backend.services.financials import jobs, parquet_store, repository
from backend.services.financials import service as service_module
from backend.services.financials.service import (
    FinancialsError,
    FinancialsService,
    build_filing_records,
    parse_period_date,
    resolve_entity_id,
)

ENTITY = "US:CIK0000320193"


@pytest.fixture
async def db_factory():
    """StaticPool 共享同一个内存库：后台任务用新会话也读写得到同一份数据。"""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def session(db_factory):
    async with db_factory() as db:
        yield db


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path: Path):
    """进程池就地执行 + Parquet 落 tmp + 任务登记簿清空。"""
    jobs.reset_jobs()

    async def inline(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("backend.core.cpu_pool.run_cpu_bound", inline)
    monkeypatch.setattr("backend.services.datalake.paths.SNAPSHOTS_ROOT", tmp_path)
    yield
    jobs.reset_jobs()


def _row(val, start, end, filed, accn):
    return {"val": val, "start": start, "end": end, "filed": filed, "accn": accn, "form": "10-K"}


def _usd(*rows):
    return {"units": {"USD": list(rows)}}


def _facts_payload():
    """毛利刚好平（revenue − cost = gross），避免勾稽噪声干扰落库断言。"""
    return {
        "facts": {
            "us-gaap": {
                "Revenues": _usd(
                    _row(1000, "2024-01-01", "2024-12-31", "2025-02-01", "a1"),
                    _row(1200, "2025-01-01", "2025-12-31", "2026-02-01", "a2"),
                ),
                "CostOfRevenue": _usd(
                    _row(600, "2024-01-01", "2024-12-31", "2025-02-01", "a1"),
                    _row(700, "2025-01-01", "2025-12-31", "2026-02-01", "a2"),
                ),
                "GrossProfit": _usd(
                    _row(400, "2024-01-01", "2024-12-31", "2025-02-01", "a1"),
                    _row(500, "2025-01-01", "2025-12-31", "2026-02-01", "a2"),
                ),
            }
        }
    }


def _submissions_payload():
    return {
        "cik": "0000320193",
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "8-K"],
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002", "0000320193-26-000003"],
                "filingDate": ["2026-02-01", "2026-05-01", ""],
                "primaryDocument": ["a1.html", "", "a3.html"],
                "reportDate": ["2025-12-31", "2026-03-31", ""],
                "fiscalYearFocus": ["2025", "", ""],
            }
        },
    }


class FakeRegistry:
    """按 action 返回预置 Result；值可以是异常对象（模拟炸穿到调用方）。"""

    def __init__(self, **by_action):
        self.by_action = by_action
        self.calls: list[tuple[str, str, dict]] = []

    async def fetch(self, source_name, action, params):
        self.calls.append((source_name, action, params))
        item = self.by_action.get(action)
        if isinstance(item, Exception):
            raise item
        return item or Result.make_error(ErrorInfo.normal("NO_FIXTURE", f"缺 {action} 桩"), source=source_name)

    @property
    def actions(self) -> list[str]:
        return [c[1] for c in self.calls]


def _ok(data):
    return Result(status=ResultStatus.SUCCESS, data=data, source="filings")


def _rate_limited():
    return Result(
        status=ResultStatus.RATE_LIMITED,
        error=ErrorInfo.rate_limited(message="SEC 429，退避中", retry_after=30),
        source="filings",
    )


def _errored(message="连接超时"):
    return Result(status=ResultStatus.ERROR, error=ErrorInfo.normal("FILINGS_FETCH_FAILED", message), source="filings")


def _healthy_registry(filings=_submissions_payload):
    return FakeRegistry(COMPANY_FACTS=_ok(_facts_payload()), SUBMISSIONS=_ok(filings()))


# ─────────────────────────────────────────
#  1. 实体与入参解析
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("US:CIK0000320193", ENTITY),
        ("us:cik320193", ENTITY),  # 大小写与零填充都归一
        ("0000320193", ENTITY),  # 10 位纯数字 = CIK
        ("600519", "CN:600519"),
        ("700", "HK:00700"),  # 港股补零
        ("HK:700", "HK:00700"),
        ("aapl", ENTITY),
    ],
)
def test_resolve_entity_id(raw, expected):
    assert resolve_entity_id(raw, symbol_to_cik={"AAPL": "0000320193"}) == expected


@pytest.mark.parametrize(
    "raw,match",
    [
        ("", "不能为空"),
        ("JP:001", "未知市场"),
        ("US:XYZ", "CIK 非法"),
        ("NVDA", "无法解析实体"),  # 没有对照表不许猜
    ],
)
def test_resolve_entity_id_rejects_ambiguous(raw, match):
    with pytest.raises(FinancialsError) as exc:
        resolve_entity_id(raw, symbol_to_cik={"AAPL": "0000320193"})
    assert (exc.value.code, exc.value.status_code) == ("fin_entity_not_found", 404)
    assert match in exc.value.message


def test_parse_period_date_is_strict():
    assert parse_period_date(None) is None
    assert parse_period_date(date(2026, 6, 30)) == date(2026, 6, 30)
    assert parse_period_date(" 2026-06-30 ") == date(2026, 6, 30)
    with pytest.raises(FinancialsError) as exc:
        parse_period_date("20260630", field="as_of")
    assert (exc.value.code, exc.value.status_code) == ("fin_bad_request", 400)
    assert "as_of" in exc.value.message


def test_build_filing_records_skips_rows_without_document():
    records = build_filing_records(ENTITY, _submissions_payload())
    assert [r["accession_no"] for r in records] == ["0000320193-26-000001"]  # 缺原文/缺日期都被丢掉
    assert records[0]["doc_url"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001/a1.html"
    assert records[0]["fiscal_year"] == 2025 and records[0]["filed_at"] == date(2026, 2, 1)
    assert records[0]["lang"] == "en" and records[0]["rag_indexed"] is False


def test_build_filing_records_fiscal_year_fallback_chain():
    payload = {
        "cik": "1326801",
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "NT 10-K"],
                "accessionNumber": ["a-1", "a-2", "a-3"],
                "filingDate": ["2026-02-01", "2026-05-01", "2026-06-01"],
                "primaryDocument": ["d1.html", "d2.html", "d3.html"],
                "reportDate": ["2025-12-31", "", ""],
                "fiscalYearFocus": ["", "2026", ""],
            }
        },
    }
    fy = [r["fiscal_year"] for r in build_filing_records(ENTITY, payload)]
    assert fy == [2025, 2026, 2026]  # focus → 报告期 → 披露年，逐级退化


def test_build_filing_records_tolerates_missing_sections():
    assert build_filing_records(ENTITY, {}) == []
    assert build_filing_records(ENTITY, {"filings": {"recent": None}}) == []
    assert build_filing_records(ENTITY, {"filings": {"recent": ["脏"]}}) == []


# ─────────────────────────────────────────
#  2. 回填：成功链路
# ─────────────────────────────────────────


async def test_backfill_writes_facts_filings_and_wide_table(session):
    registry = _healthy_registry()
    result = await FinancialsService(registry).backfill(session, entity_id=ENTITY)

    assert registry.actions == ["COMPANY_FACTS", "SUBMISSIONS"]  # 一手只经 Registry（AGENTS §4）
    assert {c[0] for c in registry.calls} == {"filings"}  # 源名是 filings，不是事实溯源标签 sec
    assert registry.calls[0][2] == {"entity_id": ENTITY}
    assert result["facts_written"] == 6 and result["filings_written"] == 1  # 3 科目 × 2 个财年
    assert result["stats"]["unmapped"] == {}
    assert result["integrity"]["failed_periods"] == {}  # 三表平 → 无标注

    rows = await repository.get_facts(session, entity_id=ENTITY)
    assert {r.concept for r in rows} == {"revenue", "cost_of_revenue", "gross_profit"}
    assert all(r.source == "sec" and r.fiscal_period == "FY" for r in rows)
    fy2025 = next(r for r in rows if r.concept == "revenue" and r.fiscal_year == 2025)
    assert fy2025.filed_as_reported == date(2026, 2, 1) and fy2025.check_failed in (None, [])

    filings = await repository.get_filings(session, entity_id=ENTITY)
    assert len(filings) == 1 and filings[0].form_type == "10-K"

    snapshot_id = result["snapshot_id"]
    assert snapshot_id.startswith("snap_financials_")
    frame = parquet_store.read_wide_table(ENTITY, "income", snapshot_id)
    assert frame.loc["revenue", "FY2025"] == 1200.0
    meta = parquet_store.read_meta(ENTITY, "income", snapshot_id)
    assert meta["basis"] == "latest" and meta["currency"] == "USD" and meta["source_mix"] == {"sec": 6}
    assert not parquet_store.table_dir(ENTITY, snapshot_id).joinpath("balance.parquet").exists()  # 空表不落盘

    job = jobs.get_job(result["job_id"])
    assert job["status"] == "success" and job["progress"] == 100


async def test_backfill_is_idempotent_on_replay(session):
    service = FinancialsService(_healthy_registry())
    await service.backfill(session, entity_id=ENTITY)
    second = await service.backfill(session, entity_id=ENTITY)
    assert second["facts_written"] == 6
    assert len(await repository.get_facts(session, entity_id=ENTITY)) == 6  # 唯一键不新增行
    assert len(await repository.get_filings(session, entity_id=ENTITY)) == 1


async def test_filings_sync_failure_does_not_block_facts(session):
    registry = FakeRegistry(COMPANY_FACTS=_ok(_facts_payload()), SUBMISSIONS=RuntimeError("子服务 500"))
    result = await FinancialsService(registry).backfill(session, entity_id=ENTITY)
    assert result["facts_written"] == 6 and result["filings_written"] == 0
    assert await repository.get_filings(session, entity_id=ENTITY) == []


async def test_filings_non_success_result_is_tolerated(session):
    registry = FakeRegistry(COMPANY_FACTS=_ok(_facts_payload()), SUBMISSIONS=_errored())
    result = await FinancialsService(registry).backfill(session, entity_id=ENTITY)
    assert result["filings_written"] == 0


# ─────────────────────────────────────────
#  3. 回填：降级与错误码
# ─────────────────────────────────────────


async def test_backfill_unregistered_source_is_501(session):
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService(FakeRegistry()).backfill(session, entity_id="HK:00700", source="hkex")
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 501)
    assert jobs.list_jobs() == []  # 未接入的源不留僵尸任务


async def test_backfill_rate_limited_maps_to_429_and_fails_job(session):
    service = FinancialsService(FakeRegistry(COMPANY_FACTS=_rate_limited()))
    with pytest.raises(FinancialsError) as exc:
        await service.backfill(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 429)
    assert "限流" in exc.value.message
    assert jobs.list_jobs()[0]["status"] == "failed"


async def test_backfill_source_error_maps_to_502(session):
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService(FakeRegistry(COMPANY_FACTS=_errored("502 网关"))).backfill(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 502)


async def test_backfill_without_xbrl_coverage_is_404(session):
    payload = {"facts": {"dei": {"EntityRegistrantName": _usd(_row(1, "2025-01-01", "2025-12-31", "2026-02-01", "a"))}}}
    service = FinancialsService(FakeRegistry(COMPANY_FACTS=_ok(payload)))
    with pytest.raises(FinancialsError) as exc:
        await service.backfill(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_no_xbrl_coverage", 404)
    assert jobs.list_jobs()[0]["status"] == "failed"  # 采集失败也得收尾，不得留 pending


async def test_transform_crash_converges_job_to_failed(session, monkeypatch):
    def boom(payload, params):
        raise ValueError("脏 payload")

    monkeypatch.setattr(jobs, "transform_payload", boom)
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService(_healthy_registry()).backfill(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_backfill_failed", 502)
    job = jobs.list_jobs()[0]
    assert job["status"] == "failed" and "脏 payload" in job["error"]


# ─────────────────────────────────────────
#  4. 任务状态机与后台会话
# ─────────────────────────────────────────


async def test_run_backfill_job_marks_success(session):
    service = FinancialsService(_healthy_registry(filings=dict))
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await service.run_backfill_job(session, job_id, entity_id=ENTITY)
    job = jobs.get_job(job_id)
    assert job["status"] == "success" and job["result"]["facts_written"] == 6


async def test_run_backfill_job_swallows_errors_into_status(session):
    service = FinancialsService(FakeRegistry(COMPANY_FACTS=_rate_limited()))
    job_id = jobs.create_job(entity_id=ENTITY, source="sec")
    await service.run_backfill_job(session, job_id, entity_id=ENTITY)  # 不许抛回事件循环
    job = jobs.get_job(job_id)
    assert job["status"] == "failed" and job["progress"] == 10  # 失败不回滚已推进的进度
    assert "限流" in job["error"]


async def test_schedule_backfill_uses_its_own_session(db_factory):
    """请求会话在返回时关闭；后台任务必须自开会话，否则回填被拦腰折断。"""
    opened = []

    def factory():
        opened.append(True)
        return db_factory()

    service = FinancialsService(_healthy_registry(filings=dict))
    job_id = service.schedule_backfill(factory, entity_id=ENTITY)
    assert opened == []  # 主协程没替它开
    assert jobs.get_job(job_id)["status"] == "pending"

    await asyncio.gather(*list(service_module._background_tasks))
    assert opened == [True]
    assert jobs.get_job(job_id)["status"] == "success"
    async with db_factory() as probe:
        assert len(await repository.get_facts(probe, entity_id=ENTITY)) == 6


# ─────────────────────────────────────────
#  5. 读路径
# ─────────────────────────────────────────


async def _seed(session):
    await FinancialsService(_healthy_registry(filings=dict)).backfill(session, entity_id=ENTITY)
    await repository.upsert_filings(
        session,
        [
            {
                "entity_id": ENTITY,
                "form_type": "10-K",
                "fiscal_year": 2025,
                "filed_at": date(2026, 2, 1),
                "accession_no": "a-1",
                "doc_url": "https://www.sec.gov/Archives/edgar/data/320193/a1.html",
                "lang": "en",
            }
        ],
    )


async def test_get_statements_returns_wide_view(session):
    await _seed(session)
    view = await FinancialsService().get_statements(session, entity_id=ENTITY, statement="income")
    assert view["periods"] == ["FY2024", "FY2025"]
    assert view["basis"] == "latest"
    assert [r["concept"] for r in view["rows"]] == ["cost_of_revenue", "gross_profit", "revenue"]
    gross = next(r for r in view["rows"] if r["concept"] == "gross_profit")
    assert gross["common_size"] == pytest.approx([40.0, 500 / 1200 * 100])

    pit = await FinancialsService().get_statements(
        session, entity_id=ENTITY, statement="income", basis="as_reported", as_of=date(2025, 6, 30)
    )
    assert pit["as_of"] == "2025-06-30"
    assert pit["periods"] == ["FY2024"]  # FY2025 当时尚未披露 → 整列不得出现


async def test_get_statements_rejects_bad_enums_and_empty_entity(session):
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService().get_statements(session, entity_id=ENTITY, statement="cashflow")
    assert (exc.value.code, exc.value.status_code) == ("fin_bad_request", 400)

    with pytest.raises(FinancialsError) as exc:
        await FinancialsService().get_statements(session, entity_id=ENTITY, basis="truth")
    assert exc.value.code == "fin_bad_request"

    with pytest.raises(FinancialsError) as exc:
        await FinancialsService().get_statements(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_entity_not_found", 404)


async def test_get_facts_and_filings_and_restatements(session):
    await _seed(session)
    service = FinancialsService()

    facts = await service.get_facts(session, entity_id=ENTITY, concept="revenue")
    assert len(facts["items"]) == 2
    assert facts["items"][0]["source"] == "sec" and facts["as_of"] is None

    filings = await service.get_filings(session, entity_id=ENTITY)
    assert filings["count"] == 1 and filings["items"][0]["accession_no"] == "a-1"

    empty = await service.get_restatements(session, entity_id=ENTITY)
    assert empty["items"] == []  # 没有重述就是空清单，不造假 diff

    with pytest.raises(FinancialsError) as exc:
        await service.get_facts(session, entity_id=ENTITY, concept="ebitda")
    assert (exc.value.code, exc.value.status_code) == ("fin_entity_not_found", 404)


async def test_restatement_path_is_visible(session):
    """重述只推进 latest，as_reported 冻结（回测读的是当时知道的数）"""
    await repository.upsert_facts(
        session,
        [
            service_module.VersionedFact(
                entity_id=ENTITY,
                concept="revenue",
                statement="income",
                unit="USD",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                value_as_reported=1200.0,
                value_latest=1300.0,
                filed_as_reported=date(2026, 2, 1),
                filed_latest=date(2027, 2, 1),
                versions=2,
                restated=True,
                source="sec",
                source_tag="Revenues",
            )
        ],
    )
    rows = await FinancialsService().get_restatements(session, entity_id=ENTITY)
    assert rows["count"] == 1
    assert rows["items"][0]["delta"] == 100.0 and round(rows["items"][0]["delta_pct"], 4) == 0.0833
    assert rows["items"][0]["label"] == "营业收入"


async def test_check_failed_flag_survives_the_write_path(session):
    """编排层算出的逐条勾稽标注必须落库（不丢数也不丢标注）"""
    payload = _facts_payload()
    payload["facts"]["us-gaap"]["GrossProfit"]["units"]["USD"].clear()
    payload["facts"]["us-gaap"]["GrossProfit"] = _usd(
        _row(100, "2025-01-01", "2025-12-31", "2026-02-01", "a2"),
        _row(400, "2024-01-01", "2024-12-31", "2025-02-01", "a1"),
    )
    registry = FakeRegistry(COMPANY_FACTS=_ok(payload), SUBMISSIONS=_ok({}))
    result = await FinancialsService(registry).backfill(session, entity_id=ENTITY)

    assert result["integrity"]["failed_periods"] == {"2025-12-31": ["gross_profit"]}
    rows = await repository.get_facts(session, entity_id=ENTITY, concept="gross_profit")
    flagged = {r.fiscal_year: r.check_failed for r in rows}
    assert flagged[2025] == ["gross_profit"] and flagged[2024] is None  # 只涂失败那一期


def test_module_singleton_is_service_free_of_registry():
    assert isinstance(service_module.financials_service, FinancialsService)
    assert service_module.FACTS_FETCHERS["sec"](ENTITY)[0] == "COMPANY_FACTS"
    assert service_module.FILINGS_FETCHERS["sec"](ENTITY)[0] == "SUBMISSIONS"


def test_filing_record_import_guard():
    """FilingRecord 的 to_dict 形状被 views 依赖，字段改名要在这里被抓到"""
    rec = FilingRecord(
        entity_id=ENTITY,
        form_type="10-K",
        fiscal_year=2025,
        filed_at=date(2026, 2, 1),
        accession_no="a",
        doc_url="u",
        lang="en",
        rag_indexed=False,
    )
    assert set(rec.to_dict()) >= {"entity_id", "form_type", "filed_at", "accession_no", "doc_url", "rag_indexed"}
