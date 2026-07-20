"""
专家团 API 端点
POST /api/v1/expert-team/analyze  - SSE 流式分析
GET  /api/v1/expert-team/scenarios - 场景模板列表
GET  /api/v1/expert-team/sessions  - 历史会话
GET  /api/v1/expert-team/sessions/{id} - 完整辩论记录
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.services.expert_team.expert_team_service import get_expert_team_service
from backend.services.expert_team.models import AnalyzeRequest

router = APIRouter(prefix="/expert-team", tags=["Expert Team"])


@router.post("/analyze")
async def analyze(request: AnalyzeRequest):
    """
    发起专家团分析 (SSE 流式响应)

    - scenario: 场景模板 ID (financial_research / code_review)
    - question: 用户问题
    - ticker: 金融域标的代码 (可选)
    - code_context: 代码域代码片段 (可选)
    """
    service = get_expert_team_service()

    # 验证场景
    try:
        service.get_scenarios()
        from backend.services.expert_team.expert_registry import get_scenario
        get_scenario(request.scenario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StreamingResponse(
        service.analyze_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/scenarios")
async def list_scenarios():
    """获取所有可用场景模板"""
    service = get_expert_team_service()
    scenarios = service.get_scenarios()
    return {"scenarios": [s.model_dump() for s in scenarios]}


@router.get("/sessions")
async def list_sessions(limit: int = 20):
    """获取历史会话列表"""
    service = get_expert_team_service()
    sessions = service.get_sessions(limit=limit)
    return {"sessions": [s.model_dump() for s in sessions]}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取完整辩论记录"""
    service = get_expert_team_service()
    session = service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return session.model_dump()
