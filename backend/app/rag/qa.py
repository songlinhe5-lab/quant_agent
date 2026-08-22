"""EARN-02 / EARN-03: 财报 / 研报 RAG 检索与问答。

检索端：复用 WebpageKnowledgeBase.embedding.cosine_distance（与 ingest_local_reports.py /
verify_vector_db.py 同一向量空间，维度由 EMBEDDING_MODEL 决定）。
回答端：检索命中片段后交给 LLM 生成带引用的回答，支持 conversation_id 追问链。

诚实降级：
- Embedding 不可用（无 API Key / 无本地模型）→ search_global_knowledge 返回 []；
- 知识库无命中 → analyze_financial_report 返回 warning 而非编造回答；
- LLM 客户端未初始化 → 返回 error_code 3001（FUTU_DISCONNECTED 同类外部依赖不可用）。
严禁任何假数据 / mock。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from backend.core.config import settings
from backend.core.database import SessionLocal
from backend.core.embeddings import get_embeddings
from backend.core.models import WebpageKnowledgeBase

logger = logging.getLogger(__name__)

# 与前端约定的知识库分类；本地研报 / 财报入库时 category="financial_report"
FINANCIAL_REPORT_CATEGORY = "financial_report"


async def search_global_knowledge(
    query: str,
    top_k: int = 5,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """余弦检索知识库片段。

    Returns:
        [{id, content, url, category, score}]，score = 1 - cosine_distance（越高越相关）。
        无 Embedding / 无命中时返回 []。
    """
    if not query or not query.strip():
        return []

    vecs = get_embeddings([query.strip()])
    if not vecs:
        logger.warning("[RAG] Embedding 服务不可用，检索降级返回空")
        return []
    q_vec = vecs[0]

    try:
        with SessionLocal() as db:
            distance = WebpageKnowledgeBase.embedding.cosine_distance(q_vec)
            stmt = select(
                WebpageKnowledgeBase.id,
                WebpageKnowledgeBase.content,
                WebpageKnowledgeBase.url,
                WebpageKnowledgeBase.category,
                distance.label("distance"),
            )
            if category:
                stmt = stmt.where(WebpageKnowledgeBase.category == category)
            stmt = stmt.order_by(distance).limit(top_k)
            rows = db.execute(stmt).mappings().all()
    except Exception as e:
        logger.error(f"[RAG] 知识库检索失败: {e}")
        return []

    results: List[Dict[str, Any]] = []
    for r in rows:
        dist = float(r["distance"]) if r["distance"] is not None else 1.0
        results.append(
            {
                "id": r["id"],
                "content": r["content"],
                "url": r["url"],
                "category": r["category"],
                "score": round(1.0 - dist, 4),
            }
        )
    return results


async def analyze_financial_report(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    llm_client: Any = None,
) -> Dict[str, Any]:
    """检索 + LLM 回答 + 引用章节。

    Returns:
        {status, answer, citations:[{content, url}], conversation_id?}
        status=error/warning/success。
    """
    if not question or not question.strip():
        return {"status": "error", "error_code": 2001, "message": "问题为空", "answer": None, "citations": []}

    if llm_client is None:
        return {
            "status": "error",
            "error_code": 3001,
            "message": "LLM 客户端未初始化（外部依赖不可用）",
            "answer": None,
            "citations": [],
        }

    chunks = await search_global_knowledge(question, top_k=5, category=FINANCIAL_REPORT_CATEGORY)
    if not chunks:
        return {
            "status": "warning",
            "message": "知识库暂无相关财报 / 研报片段（请先 ingest_local_reports 灌库）",
            "answer": None,
            "citations": [],
        }

    context = "\n\n".join(f"[来源 {c['url']}]\n{c['content']}" for c in chunks)
    sys_prompt = (
        "你是量化研究助手，仅基于提供的财报 / 研报片段作答，"
        "不得编造片段之外的数据。回答中标注引用来源（[来源 url]）。"
        "若片段不足以回答问题，明确说明信息不足。"
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": sys_prompt}]
    for h in history or []:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append(
        {
            "role": "user",
            "content": f"参考材料：\n{context}\n\n问题：{question.strip()}",
        }
    )

    model = settings.llm_model or "deepseek-v4-flash"
    try:
        resp = await llm_client.chat.completions.create(model=model, messages=messages)
        answer = resp.choices[0].message.content
    except Exception as e:
        logger.error(f"[RAG] LLM 调用失败: {e}")
        return {
            "status": "error",
            "error_code": 5000,
            "message": f"LLM 调用失败: {e}",
            "answer": None,
            "citations": [],
        }

    citations = [{"content": c["content"][:300], "url": c["url"], "score": c["score"]} for c in chunks]
    return {"status": "success", "answer": answer, "citations": citations}
