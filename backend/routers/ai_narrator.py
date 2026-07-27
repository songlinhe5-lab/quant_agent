"""AI-01 / AI-02: 异动解说员 API

端点:
- POST /ai/narrate   给定标的涨跌幅，返回数据驱动的一句话解说(带来源/置信度)
- POST /ai/stream    AI-02 解盘副驾：NDJSON 流式返回异动解说(首包 [PING]，随后 delta 逐段吐出真实文本，done 给出结构化结果；错误走 [ERROR] 不中断)
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.core.stream_utils import heartbeat_wrap
from backend.services.ai_narrator.models import NarrativeRequest
from backend.services.ai_narrator.service import AiNarratorService

logger = logging.getLogger(__name__)

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


@router.post("/stream")
async def stream_narrate(req: NarrativeRequest, request: Request):
    """AI-02 解盘副驾：流式返回异动解说(NDJSON)

    协议(每行一个 JSON 事件):
    - {"event":"ping"}                      首包占位，避免空屏
    - {"event":"delta","data":{"symbol":..,"text":..}}   逐段吐出真实 summary(打字机式，内容 100% 真实)
    - {"event":"done","data":<NarrativeResult>}          结构化结果(来源/置信度/形态胜率)
    - {"event":"error","data":".."}          下游异常，单条错误事件不中断流
    """

    async def generate():
        yield (json.dumps({"event": "ping"}) + "\n").encode("utf-8")
        try:
            result = await _service.narrate(
                symbol=req.symbol,
                change_pct=req.change_pct,
                direction=req.direction,
                threshold=req.threshold,
                include_pattern_winrate=req.include_pattern_winrate,
                pattern_winrate=req.pattern_winrate,
                pattern_name=req.pattern_name,
            )
        except Exception as exc:  # noqa: BLE001 - 透传为 error 事件，不中断流
            logger.error(f"[Narrator] 流式采集/归纳失败: {exc}")
            yield (json.dumps({"event": "error", "data": "数据源异常，解说中断"}) + "\n").encode("utf-8")
            return

        summary = result.summary or ""
        # 真实内容切片：打字机式渐进吐出，绝不编造任何文本
        step = 8
        for i in range(0, len(summary), step):
            chunk = summary[i : i + step]
            yield (json.dumps({"event": "delta", "data": {"symbol": req.symbol, "text": chunk}}) + "\n").encode("utf-8")
            await asyncio.sleep(0.02)
        yield (json.dumps({"event": "done", "data": result.model_dump(mode="json")}) + "\n").encode("utf-8")

    return StreamingResponse(
        heartbeat_wrap(generate(), request),
        media_type="application/x-ndjson",
    )
