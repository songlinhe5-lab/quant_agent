"""
专家团 API 端点
POST /api/v1/expert-team/analyze  - SSE 流式分析
GET  /api/v1/expert-team/scenarios - 场景模板列表
GET  /api/v1/expert-team/sessions  - 历史会话 (Redis 热 → PG 冷)
GET  /api/v1/expert-team/sessions/{id} - 完整辩论记录
"""

import os
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.services.expert_team.expert_team_service import get_expert_team_service
from backend.services.expert_team.models import AnalyzeRequest

router = APIRouter(prefix="/expert-team", tags=["Expert Team"])

# ─── COPILOT-08: JWT 轻量鉴权 (对齐 chat.py 口径) ───────────────
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
ALGORITHM = "HS256"
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_username(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    refresh_token: Optional[str] = Cookie(None),
) -> str:
    """从 Header (Bearer) 或 Cookie (SSR) 中提取并验证 JWT Token，返回 username"""
    token = credentials.credentials if credentials else refresh_token
    if token == "null":
        token = refresh_token
    if not token:
        raise HTTPException(status_code=401, detail="请求未携带合法 Token，拒绝访问")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token 载荷非法 (缺失 sub)")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")


@router.post("/analyze")
async def analyze(request: AnalyzeRequest, username: str = Depends(get_current_username)):
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
async def list_scenarios(username: str = Depends(get_current_username)):
    """获取所有可用场景模板"""
    service = get_expert_team_service()
    scenarios = service.get_scenarios()
    return {"scenarios": [s.model_dump() for s in scenarios]}


@router.get("/sessions")
async def list_sessions(limit: int = 20, username: str = Depends(get_current_username)):
    """获取历史会话列表 (COPILOT-05: Redis 热 → PG 冷双层查询)"""
    service = get_expert_team_service()
    sessions = await service.get_sessions(limit=limit)
    return {"sessions": [s.model_dump() for s in sessions]}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, username: str = Depends(get_current_username)):
    """获取完整辩论记录 (COPILOT-05: Redis → PG → 内存三级降级)"""
    service = get_expert_team_service()
    session = await service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return session.model_dump()
