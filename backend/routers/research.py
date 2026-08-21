"""
AI-01 (能力) · 深度研报 API 端点

- POST /research/deep-report — 触发深度研报生成
- GET  /research/meta      — Hermes 注册表元数据 (tools_count / model_name)，供投研工作台标题条
"""

from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

import backend.bootstrap.lifecycle as lifecycle
from backend.app.research.deep_research import deep_research_pipeline
from backend.core.config import settings

router = APIRouter(prefix="/research", tags=["research"])


class DeepReportRequest(BaseModel):
    topic: str
    symbols: List[str] = []


@router.get("/meta")
async def get_research_meta():
    """Hermes 注册表元数据 (tools_count / model_name)，禁止前端写死。

    数据来源：global_registry.tools 数量 + settings.llm_model (LLM_MODEL 环境变量)。
    """
    reg = getattr(lifecycle, "global_registry", None)
    return {
        "tools_count": len(reg.tools) if reg else 0,
        "model_name": settings.llm_model or "deepseek-v4-flash",
    }


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
