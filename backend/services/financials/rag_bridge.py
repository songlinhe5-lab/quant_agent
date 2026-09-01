"""
FIN-08b · 申报原文 → RAG 知识库桥
==================================

把 `DOC_TEXT` 拉回的申报全文灌进 `WebpageKnowledgeBase`，让 rag/chat 能引用原文。

设计：
- 纯同步函数（embedding 与知识库写库都是同步链路），调用方用 `asyncio.to_thread` 包裹；
- 依赖（embed / save）可注入，单测禁打真实向量服务 / PG（AGENTS §6）；
- 切分先走 textlayer 章节锚点、再按 ~2500 字滑动窗口，chunk 前缀 `[章节]`——
  与 `scripts/ingest_local_reports.py` 的 `[Header]` 前缀风格一致；
- 幂等：id = `filing_{md5(text)[:12]}_{i}`，同文档重复灌不堆积；
- EDGAR HTML 无页码概念，chunk **不伪造 source_page**（宁缺毋假，docs/28 §5.3）。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable

from backend.domain.financials import textlayer

# 与 ingest_local_reports 一致的粒度，保证知识库片段检索体验统一
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 400


def _sliding_windows(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """定长滑动窗口切一段纯文本（步长 = size - overlap）。"""
    if len(text) <= size:
        return [text] if text.strip() else []
    step = max(1, size - overlap)
    return [text[i : i + size] for i in range(0, len(text), step) if text[i : i + size].strip()]


def split_into_chunks(text: str) -> list[str]:
    """申报全文 → chunk 列表：章节锚点优先（拿得到定位信息），未命中锚点的剩余文本兜底。"""
    if not (text or "").strip():
        return []
    sections = textlayer.split_10k_sections(text)
    chunks: list[str] = []
    covered = 0
    for name in ("risk_factors", "mda", "quantitative_qualitative"):
        body = sections.get(name)
        if not body:
            continue
        chunks.extend(f"[{name}] {c}" for c in _sliding_windows(body))
        covered = max(covered, text.find(body) + len(body))
    tail = text[covered:].strip()  # 锚点未覆盖的正文（Item 1/2/8…）照灌，检索不缺料
    if tail:
        chunks.extend(_sliding_windows(tail))
    return chunks


def ingest_document(
    doc_url: str,
    text: str,
    *,
    embed: Callable[[list[str]], list[list[float]]] | None = None,
    save: Callable[[list[dict[str, Any]]], int] | None = None,
) -> dict[str, Any]:
    """切分 + 向量化 + 幂等写知识库。返回 {status, chunks_written, message?}。

    embed / save 缺省用真实实现（get_embeddings / SessionLocal 批量写）；
    任何一步失败都如实报 error，不静默丢数。
    """
    if embed is None:
        from backend.core.embeddings import get_embeddings as embed
    if save is None:
        save = _save_chunks

    chunks = split_into_chunks(text)
    if not chunks:
        return {"status": "error", "chunks_written": 0, "message": "原文为空或无法切分"}

    vectors = embed(chunks)
    if not vectors or len(vectors) != len(chunks):
        return {"status": "error", "chunks_written": 0, "message": "Embedding 服务不可用，放弃写入"}

    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    now = int(time.time())
    rows = [
        {
            "id": f"filing_{digest}_{i}",
            "url": doc_url,
            "content": chunks[i],
            "timestamp": now,
            "category": "financial_report",
            "embedding_model_version": _embedding_version(),
            "embedding": vectors[i],
        }
        for i in range(len(chunks))
    ]
    written = save(rows)
    return {"status": "success", "chunks_written": written}


def _embedding_version() -> str:
    from backend.core.config import settings

    return settings.embedding_model


def _save_chunks(rows: list[dict[str, Any]]) -> int:
    """幂等写库：同 id 先删后插（与 ingest_local_reports.force 语义一致）。"""
    from backend.core.database import SessionLocal
    from backend.core.models import WebpageKnowledgeBase

    ids = [r["id"] for r in rows]
    with SessionLocal() as db:
        db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.id.in_(ids)).delete(synchronize_session=False)
        db.bulk_save_objects([WebpageKnowledgeBase(**r) for r in rows])
        db.commit()
    return len(rows)
