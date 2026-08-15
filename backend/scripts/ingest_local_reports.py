"""
本地财报 / 研报批量灌库脚本 (AI-04 RAG 知识库补充入口)。

背景:
    原 WebpageKnowledgeBase 的唯一写入入口是 fetch_webpage (网页抓取链路)，
    导致本地 reports/ 目录下的财报 / 研报、以及对话沉淀的事实结论永远无法进入
    知识库。本脚本补齐「存量灌库」入口: 扫描 backend/reports/ 下所有支持的
    文档格式，复用与 fetch_webpage 一致的切分 + 向量化逻辑，幂等写入知识库。

使用:
    # 预览 (不写库)
    python backend/scripts/ingest_local_reports.py --dry-run

    # 实际灌库
    python backend/scripts/ingest_local_reports.py

    # 强制重灌 (覆盖已存在片段)
    python backend/scripts/ingest_local_reports.py --force

注意:
    - 向量化统一走 backend.core.embeddings.get_embeddings，保证与检索端向量空间一致。
    - 幂等: 同一文件重复运行不会堆积 (id 含文件内容 hash)。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import sys
import time

# 允许以 `python backend/scripts/ingest_local_reports.py` 方式直接运行
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.core.config import settings  # noqa: E402
from backend.core.database import SessionLocal  # noqa: E402
from backend.core.embeddings import get_embeddings  # noqa: E402
from backend.core.models import WebpageKnowledgeBase  # noqa: E402
from backend.routers.settings import _read_file_sync  # noqa: E402

SUPPORTED_EXT = [".txt", ".md", ".csv", ".pdf"]

# 切分参数与 web_scrape_tool._process_rag 保持一致，确保知识库片段粒度统一
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 400


def _split_content(content: str) -> list[str]:
    """复用 fetch_webpage 的「标题切分 + 递归滑动窗口」逻辑，返回纯文本片段列表。"""
    from langchain_text_splitters import (  # type: ignore
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    headers_to_split_on = [
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
    md_splits = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on).split_text(content)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "。", "！", "？", ".", "!", "?", "\n", "；", ";", "，", ",", " ", ""],
    )
    splits = text_splitter.split_documents(md_splits)

    docs: list[str] = []
    for s in splits:
        meta = s.metadata or {}
        headers = " > ".join([str(v) for k, v in meta.items() if str(k).startswith("Header")])
        prefix = f"[{headers}] " if headers else ""
        docs.append(prefix + s.page_content)
    return docs


def ingest_file(file_path: str, force: bool) -> tuple[int, int]:
    """灌入单个文件。返回 (成功片段数, 跳过片段数)。"""
    ext = os.path.splitext(file_path)[1].lower()
    fname = os.path.basename(file_path)
    source_url = f"local:reports/{fname}"

    content = _read_file_sync(file_path, ext)
    if not content or not content.strip():
        print(f"  ⏭️  跳过 (空内容): {fname}")
        return 0, 0

    docs = _split_content(content)
    if not docs:
        print(f"  ⏭️  跳过 (无法切分): {fname}")
        return 0, 0

    file_hash = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
    row_ids = [f"local_reports_{file_hash}_{i}" for i in range(len(docs))]

    with SessionLocal() as db:
        existing = {r.id for r in db.query(WebpageKnowledgeBase.id).filter(WebpageKnowledgeBase.id.in_(row_ids)).all()}
        if existing and not force:
            skip = len(existing)
            print(f"  ✅ 已存在，跳过整文件 ({skip} 片段): {fname}")
            return 0, skip

    vectors = get_embeddings(docs)
    if not vectors or len(vectors) != len(docs):
        print(f"  ❌ Embedding 服务不可用，放弃写入: {fname}")
        return 0, 0

    current_ts = int(time.time())
    emb_version = settings.embedding_model
    rows = [
        WebpageKnowledgeBase(
            id=row_ids[i],
            url=source_url,
            content=doc,
            timestamp=current_ts,
            category="financial_report",  # 本地研报 / 财报归入财务类，便于检索端按类过滤
            embedding_model_version=emb_version,
            embedding=vec,
        )
        for i, (doc, vec) in enumerate(zip(docs, vectors))
    ]

    with SessionLocal() as db:
        if not force:
            db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.id.in_(row_ids)).delete(
                synchronize_session=False
            )
        db.bulk_save_objects(rows)
        db.commit()

    print(f"  📥 已写入 {len(rows)} 片段: {fname}")
    return len(rows), 0


def main() -> int:
    parser = argparse.ArgumentParser(description="批量灌入 backend/reports/ 下的财报 / 研报到知识库")
    parser.add_argument("--dry-run", action="store_true", help="只统计文件与片段数，不写库")
    parser.add_argument("--force", action="store_true", help="强制重灌，覆盖已存在片段")
    args = parser.parse_args()

    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "reports"))
    if not os.path.isdir(reports_dir):
        print(f"❌ reports 目录不存在: {reports_dir}")
        return 1

    matched = []
    for ext in SUPPORTED_EXT:
        matched.extend(glob.glob(os.path.join(reports_dir, f"*{ext}")))

    if not matched:
        print(f"📭 reports/ 目录下未找到支持的文档 ({', '.join(SUPPORTED_EXT)})。无内容可灌。")
        return 0

    print(f"🔍 发现 {len(matched)} 个文档于 {reports_dir}")
    total_written = 0
    total_skipped = 0

    for fp in sorted(matched):
        if args.dry_run:
            ext = os.path.splitext(fp)[1].lower()
            try:
                content = _read_file_sync(fp, ext)
                n = len(_split_content(content)) if content.strip() else 0
                print(f"  🔎 [dry-run] {os.path.basename(fp)} -> 预计 {n} 片段")
                total_written += n
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️  [dry-run] 读取失败 {os.path.basename(fp)}: {e}")
            continue

        w, s = ingest_file(fp, force=args.force)
        total_written += w
        total_skipped += s

    print(f"\n{'[dry-run] ' if args.dry_run else ''}完成: 写入 {total_written} 片段，跳过 {total_skipped} 片段。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
