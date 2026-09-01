"""
FIN-08: 文本层（domain/financials/textlayer.py + service.get_text_diff）— 测试
==============================================================================

golden 全手算（docs/28 §5.3）：
  1. 章节切分 / 相似度 / YoY diff 可复算（Lazy Prices：重写章节排前）
  2. 定点抽取 100% 溯源：缺 source_page / source_text / value 即拒（禁无出处数字）
  3. 文本只经 Registry DOC_TEXT 拉取；不足两份 10-K 明确 404
"""

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.core.database import Base
from backend.core.financials_models import FilingRecord, FinancialFact  # noqa: F401  注册 ORM
from backend.domain.financials import textlayer
from backend.services.datasource import ErrorInfo, Result, ResultStatus
from backend.services.financials.service import FinancialsError, FinancialsService

ENTITY = "US:CIK0000320193"

OLD_10K = """
Item 1A. Risk Factors
Supply chain risk in Asia. Weather affects production.
Item 7. Management's Discussion and Analysis
Revenue grew 5% driven by iPhone sales.
Item 7A. Quantitative and Qualitative Disclosures About Market Risk
Interest rate exposure is minimal.
"""

NEW_10K = """
Item 1A. Risk Factors
Supply chain risk in Asia. Weather in Asia disrupts production schedules severely.
Item 7. Management's Discussion and Analysis
Revenue grew 12% driven by services expansion.
Item 7A. Quantitative and Qualitative Disclosures About Market Risk
Interest rate exposure is minimal.
"""


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
    await engine.dispose()


def _filing(accession, fy, form="10-K", url=None):
    return FilingRecord(
        entity_id=ENTITY,
        form_type=form,
        fiscal_year=fy,
        filed_at=date(fy + 1, 2, 1),
        accession_no=accession,
        doc_url=url or f"https://www.sec.gov/Archives/{accession}.htm",
        lang="en",
        rag_indexed=False,
    )


# ─────────────────────────────────────────
#  1. 章节切分 / 相似度 / YoY diff（手算）
# ─────────────────────────────────────────


def test_split_10k_sections_cuts_at_anchors():
    sections = textlayer.split_10k_sections(NEW_10K)
    assert set(sections) == {"risk_factors", "mda", "quantitative_qualitative"}
    assert "Supply chain risk" in sections["risk_factors"]
    assert "Revenue grew 12%" in sections["mda"]
    assert "Item 7A" not in sections["mda"]  # 下一个锚点截止
    assert sections["mda"].endswith("expansion.")  # 无下一章节尾巴


def test_split_10k_sections_missing_anchor_not_fabricated():
    assert textlayer.split_10k_sections("no anchors here") == {}
    assert textlayer.split_10k_sections("") == {}


def test_section_similarity_hand_calculated():
    assert textlayer.section_similarity("a b c", "a b c") == pytest.approx(1.0)
    assert textlayer.section_similarity("", "a") == 0.0
    # SequenceMatcher ratio = 2*M/T，共同 2 词 / 总长 5 词 → 0.8
    assert textlayer.section_similarity("a b", "a b c") == pytest.approx(0.8)


def test_yoy_diff_rewritten_first_and_fragments_present():
    out = textlayer.yoy_diff(OLD_10K, NEW_10K)
    # 风险因素与 MD&A 都改了措辞 → rewritten；7A 未动 → similar
    assert out["rewritten"] == ["risk_factors", "mda"]
    assert out["missing"] == []
    mda = next(s for s in out["sections"] if s["section"] == "mda")
    assert mda["status"] == "rewritten" and mda["similarity"] < textlayer.REWRITE_THRESHOLD
    # 变化片段须包含真实措辞变化（5% → 12%）
    joined = " ".join(f["new"] for f in mda["fragments"])
    assert "12%" in joined and "5%" not in joined


def test_yoy_diff_similar_section_has_no_fragments_and_missing_reported():
    out = textlayer.yoy_diff(OLD_10K, OLD_10K)  # 完全相同
    assert out["rewritten"] == []
    assert all(s["status"] == "similar" for s in out["sections"])

    out2 = textlayer.yoy_diff("Item 7. MD&A only old", "Item 1A. Risk Factors new")
    missing = {s["section"]: s["missing_in"] for s in out2["sections"] if s["status"] == "missing"}
    assert missing == {"mda": "new", "risk_factors": "old"}  # 单侧缺失如实报告（锚点在哪侧，另一侧即缺失）


# ─────────────────────────────────────────
#  2. 定点抽取校验（100% 溯源）
# ─────────────────────────────────────────


def test_validate_extraction_requires_page_and_text():
    ok = textlayer.validate_extraction(
        {"concept": "revenue", "value": 1200.0, "source_page": 12, "source_text": "营业额 1,200 百万"}
    )
    assert ok == {
        "concept": "revenue",
        "value": 1200.0,
        "unit": None,
        "source_page": 12,
        "source_text": "营业额 1,200 百万",
        "doc_url": None,
    }
    assert textlayer.validate_extraction({"value": 1.0, "source_page": 1, "source_text": "x"}) is not None

    assert textlayer.validate_extraction({"value": 1.0, "source_text": "x"}) is None  # 缺页码
    assert textlayer.validate_extraction({"value": 1.0, "source_page": 3}) is None  # 缺原文
    assert textlayer.validate_extraction({"source_page": 3, "source_text": "x"}) is None  # 缺值
    assert textlayer.validate_extraction({"value": 1.0, "source_page": "p3", "source_text": "x"}) is None  # 页码非法
    assert textlayer.validate_extraction({"value": 1.0, "source_page": 0, "source_text": "x"}) is None


def test_validate_extractions_batch_reports_reasons():
    out = textlayer.validate_extractions(
        [
            {"concept": "revenue", "value": 1.0, "source_page": 2, "source_text": "ok"},
            {"concept": "debt", "value": 5.0},  # 缺页码+原文
            {"value": None, "source_page": 1, "source_text": "x"},  # 缺值
        ]
    )
    assert out["total"] == 3 and len(out["accepted"]) == 1
    reasons = {r["index"]: r["reason"] for r in out["rejected"]}
    assert reasons[1] == "缺 source_page" and reasons[2] == "缺 value"


def test_rag_citation_requires_url_and_content():
    assert textlayer.rag_citation({"url": "https://x/a.pdf", "content": "quote text", "source_page": 7}) == {
        "url": "https://x/a.pdf",
        "quote": "quote text",
        "source_page": 7,
        "category": None,
        "score": None,
    }
    assert textlayer.rag_citation({"content": "no url"}) is None
    assert textlayer.rag_citation({"url": "https://x", "content": "  "}) is None


# ─────────────────────────────────────────
#  3. service.get_text_diff 编排
# ─────────────────────────────────────────


class FakeRegistry:
    """按完整 doc_url 分发（与 service 实际请求参数一致）。"""

    def __init__(self, by_url):
        self.by_url = by_url
        self.calls: list[tuple[str, str, dict]] = []

    async def fetch(self, source_name, action, params):
        self.calls.append((source_name, action, params))
        hit = self.by_url.get(params.get("doc_url"))
        if isinstance(hit, Result):
            return hit
        return Result(status=ResultStatus.SUCCESS, data={"text": hit, "url": params.get("doc_url")}, source="filings")


async def _seed(session):
    session.add_all([_filing("accn-2024", 2024), _filing("accn-2025", 2025), _filing("q1-2025", 2025, form="10-Q")])
    await session.commit()


async def test_get_text_diff_auto_picks_last_two_10k(session):
    await _seed(session)
    url_of = lambda a: f"https://www.sec.gov/Archives/{a}.htm"  # noqa: E731
    registry = FakeRegistry({url_of("accn-2024"): OLD_10K, url_of("accn-2025"): NEW_10K})
    out = await FinancialsService(registry).get_text_diff(session, entity_id=ENTITY)

    # 10-Q 被过滤；DOC_TEXT 只取两份 10-K 原文
    assert registry.calls == [("filings", "DOC_TEXT", {"doc_url": url_of(a)}) for a in ("accn-2024", "accn-2025")]
    assert out["old"]["accession_no"] == "accn-2024" and out["new"]["accession_no"] == "accn-2025"
    assert out["rewritten"] == ["risk_factors", "mda"]  # 与域层 golden 同源


async def test_get_text_diff_rejects_without_two_10k_or_bad_accn(session):
    registry = FakeRegistry({})
    service = FinancialsService(registry)

    with pytest.raises(FinancialsError) as exc:
        await service.get_text_diff(session, entity_id=ENTITY)  # 空库
    assert (exc.value.code, exc.value.status_code) == ("fin_not_found", 404)

    await _seed(session)
    with pytest.raises(FinancialsError) as exc:
        await service.get_text_diff(session, entity_id=ENTITY, accession_a="no-such-accn")
    assert (exc.value.code, exc.value.status_code) == ("fin_not_found", 404)
    assert registry.calls == []  # 校验失败不发请求


async def test_get_text_diff_source_failure_maps_to_degraded(session):
    await _seed(session)
    registry = FakeRegistry(
        {
            "https://www.sec.gov/Archives/accn-2024.htm": Result(
                status=ResultStatus.RATE_LIMITED,
                error=ErrorInfo.rate_limited(message="SEC 429", retry_after=30),
                source="filings",
            )
        }
    )
    with pytest.raises(FinancialsError) as exc:
        await FinancialsService(registry).get_text_diff(session, entity_id=ENTITY)
    assert (exc.value.code, exc.value.status_code) == ("fin_source_degraded", 429)


async def test_service_validate_extractions_passthrough():
    out = await FinancialsService(None).validate_extractions(
        [{"value": 3.0, "source_page": 4, "source_text": "页四"}, {"value": 1.0}]
    )
    assert len(out["accepted"]) == 1 and out["rejected"][0]["index"] == 1
