"""
EARN-02 / EARN-03: 财报 / 研报 RAG 路由。

- POST /api/v1/rag/chat : 财报问答（检索 + LLM 带引用回答 + 追问链）
- GET  /api/v1/rag/search: 语义检索增强（返回相关财报 / 研报片段，供前端"相关章节"展示）
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.app.rag.qa import analyze_financial_report, search_global_knowledge
from backend.routers.chat import get_current_username

router = APIRouter(prefix="/api/v1/rag", tags=["RAG"])


class RagChatMessage(BaseModel):
    role: str
    content: str


class RagChatRequest(BaseModel):
    question: str
    history: Optional[List[RagChatMessage]] = None
    conversation_id: Optional[str] = None


@router.post("/chat")
async def rag_chat(
    req: RagChatRequest,
    username: str = Depends(get_current_username),
):
    """财报 / 研报问答：检索知识库 + LLM 生成带引用回答。

    无 LLM / 无知识库命中时返回明确 error/warning，不编造数据。
    """
    from backend.bootstrap.lifecycle import global_llm_client

    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    result = await analyze_financial_report(
        question=req.question,
        history=history,
        llm_client=global_llm_client,
    )
    # 透传 conversation_id，便于前端维持追问链
    if req.conversation_id:
        result["conversation_id"] = req.conversation_id
    return result


@router.get("/search")
async def rag_search(
    q: str = Query(..., description="检索问题 / 关键词"),
    top_k: int = Query(5, ge=1, le=20),
    category: Optional[str] = Query(None, description="按知识库分类过滤，如 financial_report"),
    username: str = Depends(get_current_username),
):
    """EARN-03 语义检索增强：返回与 query 最相关的知识库片段（不调用 LLM）。"""
    results = await search_global_knowledge(q, top_k=top_k, category=category)
    return {
        "status": "success" if results else "warning",
        "data": results,
        "message": None if results else "知识库无相关片段",
    }
