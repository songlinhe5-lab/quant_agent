"""
AI-01 (能力) · 深度研报 API 端点

- POST /research/deep-report — 触发深度研报生成
"""

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from backend.services.deep_research import deep_research_pipeline

router = APIRouter(prefix="/research", tags=["research"])


class DeepReportRequest(BaseModel):
    topic: str
    symbols: List[str] = []


@router.post("/deep-report")
async def generate_deep_report(req: DeepReportRequest):
    """触发深度研报生成 (SSE 流式返回进度)"""
    report = await deep_research_pipeline.run(req.topic, req.symbols)
    return {
        "topic": report.topic,
        "symbols": report.symbols,
        "executive_summary": report.executive_summary,
        "findings": [{"theme": f.theme, "summary": f.summary, "relevance": f.relevance} for f in report.findings],
        "deep_analysis": report.deep_analysis,
        "markdown_content": report.markdown_content,
        "chart_configs": report.chart_configs,
        "references": report.references,
    }
