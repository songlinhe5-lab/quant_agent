"""幂等迁移：sentiment_records 新增零售热度因子列（C.1）。

背景：
  C.1 在 SentimentRecord 模型新增 retail_heat_change_pct / retail_heat_total，
  但生产库为已存在旧表（SQLAlchemy create_all 不会给已有表加列），查询报
  UndefinedColumn。当时 Alembic 迁移链历史已损坏（多个 None head），故不用 alembic，
  改用独立幂等 DDL（PostgreSQL 15+ ADD COLUMN IF NOT EXISTS）。

  2026-08-31 迁移链已修复为单链，`sent01` 并入主链且改为方言无关的 inspector 判列加列，
  `alembic upgrade head` 可正常执行。本脚本保留作**兜底/手工修复**用（与 sent01 幂等，
  两者都执行不会冲突）。

用法：
  DATABASE_URL=... python -m backend.scripts.migrate_sentiment_retail_heat
  或经部署流程执行。幂等：可重复执行，已加列则跳过。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import create_engine, inspect, text  # noqa: E402

TARGET_COLUMNS = {
    "retail_heat_change_pct": "FLOAT",  # PG 中 FLOAT≈DOUBLE PRECISION，SQLite 亦接受
    "retail_heat_total": "INTEGER",
}
TABLE = "sentiment_records"


def main() -> int:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("❌ 缺少 DATABASE_URL 环境变量")
        return 1
    engine = create_engine(db_url)
    with engine.connect() as conn:
        insp = inspect(engine)
        existing = {c["name"] for c in insp.get_columns(TABLE)}
        print(f"表 {TABLE} 现有列: {sorted(existing)}")
        for col, ctype in TARGET_COLUMNS.items():
            if col in existing:
                print(f"  ✅ {col} 已存在，跳过")
                continue
            # 已用 existing 检查兜底（幂等），不再用 IF NOT EXISTS（PG 15+ 才支持，SQLite 不支持）
            conn.execute(text(f"ALTER TABLE {TABLE} ADD COLUMN {col} {ctype}"))
            print(f"  ➕ 已添加 {col} ({ctype})")
        conn.commit()
    # 验证
    with engine.connect() as conn:
        insp = inspect(engine)
        after = {c["name"] for c in insp.get_columns(TABLE)}
        missing = [c for c in TARGET_COLUMNS if c not in after]
        if missing:
            print(f"❌ 迁移后仍缺列: {missing}")
            return 1
        print(f"✅ 迁移完成，表 {TABLE} 现有列: {sorted(after)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
