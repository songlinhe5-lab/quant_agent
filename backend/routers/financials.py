"""
FIN-04 · 财报看板 API（docs/28 §六）

只做入参校验与转发（AGENTS §4）：业务在 `services/financials`，Facade 收口在
`services/datasource/business/fundamental`。响应统一 `{status,message,data,timestamp}`，
错误另带 `error_code`。回填一律异步返回 job_id，禁止在请求里等采集。
"""

from __future__ import annotations

from typing import Any, Coroutine, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.routers.financials_schemas import (
    BASIS_PATTERN,
    BackfillBatchRequest,
    BackfillRequest,
    err_envelope,
    ok_envelope,
)
from backend.services.datasource.business.fundamental import fundamental_data_service as facade
from backend.services.financials import jobs
from backend.services.financials.service import FinancialsError

router = APIRouter(prefix="/financials", tags=["Financials"])
# 注：会话由 Facade / Service 自管（一次请求一个 `AsyncSessionLocal`），
# 路由不再 `Depends(get_async_db)`，避免白白多开一个连接。


async def _forward(coro: Coroutine[Any, Any, Any]):
    """成功走 200 信封，`FinancialsError` 按 error_code 翻译状态码；其余异常交给框架。"""
    try:
        return ok_envelope(await coro)
    except FinancialsError as exc:
        return err_envelope(exc.code, exc.message, exc.status_code)


@router.get("/statements/{entity}")
async def get_statements(
    entity: str,
    statement: str = Query("income", description="income / balance / cash"),
    basis: str = Query("latest", pattern=BASIS_PATTERN, description="口径，必须让前端看得见"),
    as_of: Optional[str] = Query(None, description="PIT 日期 YYYY-MM-DD"),
    limit: int = Query(500, ge=1, le=5000),
):
    return await _forward(facade.get_statements(entity, statement=statement, basis=basis, as_of=as_of, limit=limit))


@router.get("/facts/{entity}")
async def get_facts(
    entity: str,
    concept: Optional[str] = Query(None, description="标准科目名"),
    statement: Optional[str] = Query(None),
    as_of: Optional[str] = Query(None, description="传了即 PIT 查询（filed_as_reported <= as_of）"),
    limit: int = Query(500, ge=1, le=5000),
):
    return await _forward(facade.get_facts(entity, concept=concept, statement=statement, as_of=as_of, limit=limit))


@router.get("/filings/{entity}")
async def get_filings(
    entity: str,
    limit: int = Query(100, ge=1, le=500),
):
    return await _forward(facade.get_filings(entity, limit=limit))


@router.get("/restatements/{entity}")
async def get_restatements(
    entity: str,
    limit: int = Query(200, ge=1, le=1000),
):
    return await _forward(facade.get_restatements(entity, limit=limit))


@router.post("/backfill")
async def submit_backfill(req: BackfillRequest):
    """历史回填：登记任务 → 挂后台 → 立刻返回 job_id（采集 + 归一是重活）。"""
    try:
        data = await facade.backfill(req.entity, source=req.source)
    except FinancialsError as exc:
        return err_envelope(exc.code, exc.message, exc.status_code)
    return ok_envelope(data, "backfill scheduled")


@router.get("/jobs/{job_id}")
async def get_backfill_job(job_id: str):
    """回填任务状态（pending / running / success / failed）；重启后内存 miss 落库查快照。"""
    job = await jobs.get_job_any(job_id)
    if job is None:
        return err_envelope("fin_job_not_found", f"任务不存在: {job_id}")
    return ok_envelope(job)


@router.get("/analytics/{entity}")
async def get_analytics(
    entity: str,
    as_of: Optional[str] = Query(None, description="PIT 日期 YYYY-MM-DD"),
    market_cap: Optional[float] = Query(None, description="市值（行情侧传入，引擎禁止自估）"),
):
    """分析引擎：DuPont / 现金流质量 / Piotroski F · Altman Z · Beneish M（docs/28 §5.1）。"""
    return await _forward(facade.get_analytics(entity, as_of=as_of, market_cap=market_cap))


@router.get("/peers/{entity}")
async def get_peers(
    entity: str,
    concept: str = Query("revenue", description="用于截面的标准科目（如 revenue / total_assets）"),
    peer_set: Optional[str] = Query(None, description="手工固定同业清单（逗号分隔实体，如 aapl,msft）"),
):
    """同业中位数与截面分位（docs/28 §5.2）；样本 < 8 家 → 422 不出分位结论。"""
    return await _forward(facade.get_peers(entity, concept=concept, peer_set=peer_set))


@router.get("/text/diff/{entity}")
async def get_text_diff(
    entity: str,
    accession_a: Optional[str] = Query(None, description="旧年报 accession_no（缺省自动取最近两份 10-K）"),
    accession_b: Optional[str] = Query(None, description="新年报 accession_no"),
):
    """MD&A / 风险因素 YoY diff（docs/28 §5.3，Lazy Prices 依据）。"""
    return await _forward(facade.get_text_diff(entity, accession_a=accession_a, accession_b=accession_b))


class ExtractionItem(BaseModel):
    """港A PDF 定点抽取单项：source_page / source_text / value 缺一即拒（docs/28 §5.3）。"""

    concept: str = ""
    value: Any = None
    unit: Optional[str] = None
    source_page: Optional[int] = None
    source_text: Optional[str] = None
    doc_url: Optional[str] = None


class ExtractionBatch(BaseModel):
    items: list[ExtractionItem]


@router.post("/text/extractions")
async def validate_extractions(batch: ExtractionBatch):
    """定点抽取强制溯源校验：accepted 规范化清单 + rejected 原因（禁无出处数字）。"""
    return await _forward(facade.validate_extractions([it.model_dump() for it in batch.items]))


@router.post("/filings/{entity}/{accession}/ingest")
async def ingest_filing(entity: str, accession: str):
    """FIN-08b：申报原文 → RAG 知识库（切分 + 向量化 + 幂等写，成功回写 rag_indexed）。"""
    return await _forward(facade.ingest_filing(entity, accession_no=accession))


@router.get("/coverage/{entity}")
async def get_coverage(
    entity: str,
    years: int = Query(10, ge=1, le=30, description="回看窗口（自然年，默认 10 年）"),
):
    """FIN-09：核心科目 × 最近 N 财年覆盖盘点（缺失显式列出，验收基准 <5%）。"""
    return await _forward(facade.get_coverage(entity, years=years))


@router.post("/backfill-batch")
async def backfill_batch(req: BackfillBatchRequest):
    """FIN-09：目标池批量回填，逐实体挂后台任务立刻返回 job_id 清单。"""
    return ok_envelope(facade.backfill_batch([e.strip() for e in req.entities], source=req.source))
