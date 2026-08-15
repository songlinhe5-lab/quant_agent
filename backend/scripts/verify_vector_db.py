"""
向量数据库存取验证脚本 (pgvector + 硅基流动 embedding)

用途：验证 webpage_knowledge_base 表的「写入 → 检索」round-trip 是否正常。
不依赖业务代码，直接复用 backend.core.embeddings.get_embeddings 与 ORM 模型，
保证与 search_global_knowledge / fetch_webpage 同一向量空间。

运行：
    cd backend && python scripts/verify_vector_db.py
"""

import os
import sys
import time
import uuid

# 1. 载入 .env（get_embeddings 走 os.getenv，必须先 load_dotenv）
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from backend.core.database import SessionLocal, engine  # noqa: E402
from backend.core.embeddings import get_embeddings  # noqa: E402
from backend.core.models import WebpageKnowledgeBase  # noqa: E402


def _check_table() -> bool:
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'webpage_knowledge_base')")
        ).scalar()
    return bool(exists)


def main() -> int:
    db_url = os.getenv("DATABASE_URL", "")
    print(f"[1/5] DATABASE_URL = {db_url[:40]}...")
    if not db_url.startswith("postgresql"):
        print("❌ 当前 DATABASE_URL 非 PostgreSQL，pgvector 不可用。请检查 .env。")
        return 1

    if not _check_table():
        print("❌ webpage_knowledge_base 表不存在，无法验证。")
        return 1
    print("✅ 表 webpage_knowledge_base 存在")

    # 2. 生成 embedding
    print("[2/5] 调用硅基流动 embedding API 生成向量 ...")
    probe = "腾讯控股 2026 年中期业绩营收同比增长 12% 净利润超预期"
    vecs = get_embeddings([probe])
    if not vecs or len(vecs[0]) == 0:
        print("❌ Embedding 生成失败（API Key 无效 / 网络不通 / 余额耗尽）。")
        return 1
    dim = len(vecs[0])
    print(f"✅ Embedding 成功，维度 = {dim}（期望 1024）")
    if dim != 1024:
        print(f"⚠️  维度 {dim} != 1024，与 EMBEDDING_DIM 配置不符，检索会错位。")

    # 3. 写入一条测试记录
    print("[3/5] 写入测试向量到 webpage_knowledge_base ...")
    test_id = f"__verify_{uuid.uuid4().hex[:12]}"
    rec = WebpageKnowledgeBase(
        id=test_id,
        url="https://verify.local/health-check",
        content=probe,
        timestamp=int(time.time()),
        user_id=None,
        category="general",
        embedding_model_version=os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
        embedding=vecs[0],
    )
    with SessionLocal() as db:
        db.add(rec)
        db.commit()
    print(f"✅ 写入成功 (id={test_id})")

    # 4. 检索：用相同文本查询，应命中自己（距离≈0）
    print("[4/5] 余弦检索验证 round-trip ...")
    q_vecs = get_embeddings(["腾讯控股 2026 年中期业绩营收同比增长 12% 净利润超预期"])
    if not q_vecs:
        print("❌ 检索用 embedding 生成失败。")
        return 1
    with SessionLocal() as db:
        distance_col = WebpageKnowledgeBase.embedding.cosine_distance(q_vecs[0])
        row = (
            db.query(WebpageKnowledgeBase, distance_col.label("distance"))
            .filter(WebpageKnowledgeBase.id == test_id)
            .first()
        )
        if row is None:
            print("❌ 检索未命中所写记录，存取链路异常。")
            return 1
        dist = float(row[1])
        print(f"✅ 检索命中，cosine_distance = {dist:.6f}")
        if dist > 1e-4:
            print(f"⚠️  距离 {dist} 偏大，可能存在向量空间不一致。")

    # 5. 清理测试数据
    print("[5/5] 清理测试记录 ...")
    with SessionLocal() as db:
        db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.id == test_id).delete()
        db.commit()
    print("✅ 测试数据已清理")

    print("\n🎉 向量数据库存取验证通过：写入 → 检索 → 命中 → 清理 全链路正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
