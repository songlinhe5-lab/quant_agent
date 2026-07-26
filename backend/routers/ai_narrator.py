"""AI-01: 异动解说员 API

端点:
- POST /ai/narrate   给定标的涨跌幅，返回数据驱动的一句话解说(带来源/置信度)
"""

from fastapi import APIRouter

from backend.services.ai_narrator.models import NarrativeRequest
from backend.services.ai_narrator.service import AiNarratorService

router = APIRouter(prefix="/ai", tags=["AI-01 异动解说员"])
_service = AiNarratorService()


@router.post("/narrate")
async def narrate(req: NarrativeRequest):
    """对异动标的生成一句话数据驱动解说"""
    result = await _service.narrate(
        symbol=req.symbol,
        change_pct=req.change_pct,
        direction=req.direction,
        threshold=req.threshold,
        include_pattern_winrate=req.include_pattern_winrate,
        pattern_winrate=req.pattern_winrate,
        pattern_name=req.pattern_name,
    )
    return {"status": "success", "data": result.model_dump(mode="json")}
