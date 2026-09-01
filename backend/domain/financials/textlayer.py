"""
FIN-08 · 文本层引擎（docs/28 §5.3，零 IO 纯函数）
=================================================

三条能力，全部确定性可复算，LLM 只在管线外层参与：
  1. MD&A / 风险因素 YoY diff（Lazy Prices, JF 2020：年报措辞变化有预测力）
  2. 港A PDF 定点抽取校验：抽取值强制带 `source_page` + `source_text`，缺一即拒
  3. RAG 引用定位：引用块带 doc_url / accession / page，前端可跳回原文

红线（AGENTS §5）：不允许任何数字/结论没有出处；章节无对应帧/文本就明说，不猜。
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Mapping

# 10-K 章节锚点（EDGAR 结构性标题）。按 appearance 顺序匹配首个标题行。
_SECTION_ANCHORS: dict[str, re.Pattern[str]] = {
    "risk_factors": re.compile(r"^\s*item\s+1a[.\s]*(risk factors)?", re.IGNORECASE | re.MULTILINE),
    "mda": re.compile(
        r"^\s*item\s+7(?!\s*a\b)[.\s]*(management'?s discussion and analysis)?",
        re.IGNORECASE | re.MULTILINE,
    ),
    "quantitative_qualitative": re.compile(r"^\s*item\s+7a[.\s]*", re.IGNORECASE | re.MULTILINE),
}

# 相似度低于此阈值 → 章节被判定「重写」（Lazy Prices 的显著变化信号）
REWRITE_THRESHOLD = 0.80


def split_10k_sections(text: str) -> dict[str, str]:
    """10-K 全文 → {章节: 文本}。锚点缺失的章节不产出（宁缺毋假）。"""
    if not text:
        return {}
    hits: list[tuple[int, str]] = []
    for name, pat in _SECTION_ANCHORS.items():
        m = pat.search(text)
        if m:
            hits.append((m.start(), name))
    hits.sort()
    out: dict[str, str] = {}
    for i, (start, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        out[name] = text[start:end].rstrip()  # 去掉切分残留的尾部空白，正文锚点行保留
    return out


def _changed_fragments(a: str, b: str, *, max_frags: int = 20) -> list[dict[str, str]]:
    """词级 diff → 变化片段（新增/删除各保留上下文）。"""
    sm = difflib.SequenceMatcher(None, a.split(), b.split(), autojunk=False)
    frags: list[dict[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        frags.append(
            {
                "op": tag,
                "old": " ".join(a.split()[i1:i2])[:300],
                "new": " ".join(b.split()[j1:j2])[:300],
            }
        )
        if len(frags) >= max_frags:
            break
    return frags


def section_similarity(old: str, new: str) -> float:
    """章节相似度 0~1（词级 SequenceMatcher ratio，可复算）。空文本按 0 处理。"""
    if not old or not new:
        return 0.0
    return difflib.SequenceMatcher(None, old.split(), new.split(), autojunk=False).ratio()


def yoy_diff(old_text: str, new_text: str) -> dict[str, Any]:
    """相邻两年年报 YoY diff：逐章节相似度 + 变化片段 + 重写章节清单。

    相似度 ≥ REWRITE_THRESHOLD 视为措辞基本不变（不出片段，省算力）；
    章节只在两年都存在时才 diff，单侧缺失如实标 missing。
    """
    old_sections, new_sections = split_10k_sections(old_text), split_10k_sections(new_text)
    sections: list[dict[str, Any]] = []
    for name in sorted(set(old_sections) | set(new_sections)):
        old, new = old_sections.get(name, ""), new_sections.get(name, "")
        if not old or not new:
            sections.append({"section": name, "status": "missing", "missing_in": "new" if not new else "old"})
            continue
        sim = section_similarity(old, new)
        sections.append(
            {
                "section": name,
                "status": "rewritten" if sim < REWRITE_THRESHOLD else "similar",
                "similarity": round(sim, 4),
                "fragments": [] if sim >= REWRITE_THRESHOLD else _changed_fragments(old, new),
            }
        )
    # 重写章节排前（Lazy Prices 信号强度）
    sections.sort(key=lambda s: s.get("similarity", 1.0))
    return {
        "sections": sections,
        "rewritten": [s["section"] for s in sections if s.get("status") == "rewritten"],
        "missing": [s["section"] for s in sections if s.get("status") == "missing"],
    }


# ── 定点抽取校验（港A PDF；docs/28 §5.3 诚实性红线）─────────────────


def validate_extraction(item: Mapping[str, Any]) -> dict[str, Any] | None:
    """单个 LLM 抽取值 → 通过返回规范化条目；缺 source_page / source_text / value 即 None（丢弃）。"""
    value = item.get("value")
    page = item.get("source_page")
    text = (item.get("source_text") or "").strip()
    if value is None or page is None or not text:
        return None
    try:
        page = int(page)
    except (TypeError, ValueError):
        return None
    if page < 1:
        return None
    return {
        "concept": str(item.get("concept", "")),
        "value": value,
        "unit": item.get("unit"),
        "source_page": page,
        "source_text": text,
        "doc_url": item.get("doc_url"),
    }


def validate_extractions(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    """批量校验：accepted 规范化清单 + rejected 原因清单（100% 溯源，缺一即拒）。"""
    accepted, rejected = [], []
    for i, item in enumerate(items):
        ok = validate_extraction(item)
        if ok is None:
            reason = "缺 source_page/source_text/value" if not isinstance(item, Mapping) else _reject_reason(item)
            rejected.append({"index": i, "reason": reason})
        else:
            accepted.append(ok)
    return {"accepted": accepted, "rejected": rejected, "total": len(items)}


def _reject_reason(item: Mapping[str, Any]) -> str:
    if item.get("value") is None:
        return "缺 value"
    if item.get("source_page") is None:
        return "缺 source_page"
    if not (item.get("source_text") or "").strip():
        return "source_text 为空"
    return "source_page 非法"


# ── RAG 引用定位（docs/28 §5.3：引用可跳回原文页）────────────────────


def rag_citation(chunk: Mapping[str, Any]) -> dict[str, Any] | None:
    """知识库 chunk → 前端跳原文的定位结构。缺 url 的 chunk 不产出引用（禁无出处）。"""
    url = (chunk.get("url") or "").strip()
    content = (chunk.get("content") or "").strip()
    if not url or not content:
        return None
    return {
        "url": url,
        "quote": content[:200],
        "source_page": chunk.get("source_page"),
        "category": chunk.get("category"),
        "score": chunk.get("score"),
    }
