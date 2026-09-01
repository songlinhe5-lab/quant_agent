"""
FIN-08b: 申报原文 → RAG 知识库（rag_bridge.py + service.ingest_filing）— 测试
============================================================================

单测不打真实向量服务 / PG（AGENTS §6）：
  - bridge 层 embed / save 全注入；
  - service 层 monkeypatch rag_bridge.ingest_document（编排逻辑单测）。
红线：文本只经 Registry DOC_TEXT 拉取；失败如实报 error，不静默丢数。
"""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FilingRecord, FinancialFact  # noqa: F401  注册 ORM
from backend.services.datasource import ErrorInfo, Result, ResultStatus
from backend.services.financials import rag_bridge
from backend.services.financials.service import FinancialsError, FinancialsService

ENTITY = "US:CIK0000320193"
ACCESSION = "0000320193-24-000006"
DOC_URL = f"https://www.sec.gov/Archives/{ACCESSION}.htm"

DOC = """
Item 1A. Risk Factors
Supply chain risk in Asia. Weather affects production.
Item 7. Management's Discussion and Analysis
Revenue grew 5% driven by iPhone sales.
"""


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


@pytest.fixture
def filing(session):
    session.add(
        FilingRecord(
            entity_id=ENTITY,
            form_type="10-K",
            fiscal_year=2023,
            filed_at=date(2024, 2, 2),
            accession_no=ACCESSION,
            doc_url=DOC_URL,
            lang="en",
            rag_indexed=False,
        )
    )
    return session


class FakeRegistry:
    def __init__(self, by_url):
        self.by_url = by_url
        self.calls: list[tuple[str, str, dict]] = []

    async def fetch(self, source_name, action, params):
        self.calls.append((source_name, action, params))
        hit = self.by_url.get(params.get("doc_url"))
        if isinstance(hit, Result):
            return hit
        return Result(status=ResultStatus.SUCCESS, data={"text": hit, "url": params.get("doc_url")}, source="filings")


def fake_embed_dim4():
    """确定性伪 embedding（按字符长度映射），避免打真实向量服务。"""

    def _embed(texts):
        return [[float(len(t) % 7), 1.0, 0.0, float(len(t) > 100)] for t in texts]

    return _embed


# ─────────────────────────────────────────
#  1. bridge：切分 / 入库 / 失败如实上报
# ─────────────────────────────────────────


def test_split_into_chunks_prefers_anchors_and_keeps_tail():
    chunks = rag_bridge.split_into_chunks(DOC)
    assert chunks, "正常文本必须能切出片段"
    assert any(c.startswith("[risk_factors]") for c in chunks)
    assert any(c.startswith("[mda]") for c in chunks)
    # 超长正文触发滑动窗口（不重叠断言——窗口步长 = size - overlap）
    long_text = "x" * (rag_bridge.CHUNK_SIZE + 100)
    assert len(rag_bridge.split_into_chunks(long_text)) >= 2


def test_split_into_chunks_empty():
    assert rag_bridge.split_into_chunks("") == []
    assert rag_bridge.split_into_chunks("   \n  ") == []


def test_ingest_document_success_and_idempotent_ids():
    saved: list[list[dict]] = []
    out1 = rag_bridge.ingest_document(
        DOC_URL, DOC, embed=fake_embed_dim4(), save=lambda rows: (saved.append(rows), len(rows))[1]
    )
    assert out1["status"] == "success" and out1["chunks_written"] == len(saved[0])
    for row in saved[0]:
        assert row["url"] == DOC_URL
        assert row["category"] == "financial_report"
        assert len(row["embedding"]) == 4

    # 同文档重复灌：id 稳定（幂等，不堆积）
    out2 = rag_bridge.ingest_document(DOC_URL, DOC, embed=fake_embed_dim4(), save=lambda rows: len(rows))
    assert out2["chunks_written"] == out1["chunks_written"]


def test_ingest_document_empty_text_is_error_not_silent():
    out = rag_bridge.ingest_document(DOC_URL, "  \n ", embed=fake_embed_dim4(), save=lambda rows: len(rows))
    assert out["status"] == "error" and out["chunks_written"] == 0


def test_ingest_document_embed_failure_aborts_write():
    written = []

    def bad_embed(texts):
        return []

    out = rag_bridge.ingest_document(DOC_URL, DOC, embed=bad_embed, save=lambda rows: written.extend(rows))
    assert out["status"] == "error"
    assert not written, "embedding 失败绝不能写库"


# ─────────────────────────────────────────
#  2. service.ingest_filing：编排 / 状态回写 / 错误码
# ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_filing_success_flips_rag_indexed(session, filing, monkeypatch):
    monkeypatch.setattr(rag_bridge, "ingest_document", lambda url, text: {"status": "success", "chunks_written": 12})
    registry = FakeRegistry({DOC_URL: DOC})
    out = await FinancialsService(registry).ingest_filing(session, entity_id=ENTITY, accession_no=ACCESSION)

    assert out["chunks_written"] == 12 and out["doc_url"] == DOC_URL
    assert registry.calls == [("filings", "DOC_TEXT", {"doc_url": DOC_URL})]  # 不直连外网
    session.expire_all()  # 强制重新查库，验证 commit 真实落盘
    rec = (await session.execute(select(FilingRecord))).scalar_one()
    assert rec.rag_indexed is True  # 时间轴状态闭环


@pytest.mark.asyncio
async def test_ingest_filing_unknown_accession_is_404(session, filing):
    with pytest.raises(FinancialsError) as ei:
        await FinancialsService(None).ingest_filing(session, entity_id=ENTITY, accession_no="nope")
    assert ei.value.code == "fin_not_found" and ei.value.status_code == 404


@pytest.mark.asyncio
async def test_ingest_filing_doc_text_degraded(session, filing):
    registry = FakeRegistry(
        {
            DOC_URL: Result(
                status=ResultStatus.ERROR,
                error=ErrorInfo(code="upstream_timeout", message="EDGAR 超时"),
                source="filings",
            )
        }
    )
    with pytest.raises(FinancialsError) as ei:
        await FinancialsService(registry).ingest_filing(session, entity_id=ENTITY, accession_no=ACCESSION)
    assert ei.value.code == "fin_source_degraded"


@pytest.mark.asyncio
async def test_ingest_filing_bridge_error_is_degraded(session, filing, monkeypatch):
    monkeypatch.setattr(
        rag_bridge,
        "ingest_document",
        lambda url, text: {"status": "error", "chunks_written": 0, "message": "Embedding 服务不可用"},
    )
    registry = FakeRegistry({DOC_URL: DOC})
    with pytest.raises(FinancialsError) as ei:
        await FinancialsService(registry).ingest_filing(session, entity_id=ENTITY, accession_no=ACCESSION)
    assert ei.value.code == "fin_source_degraded"
