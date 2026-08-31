"""add retail_heat columns to sentiment_records

C.1 热度因子接入研判层新增 retail_heat_change_pct / retail_heat_total 两列。
生产库为已存在的旧表（create_all 不会给已有表加列），需显式迁移。

Revision ID: sent01
Revises: fe05b_frontend_logs
Create Date: 2026-08-22

⚠️ 2026-08-31 修复：原实现是 `down_revision = None` 的独立 head + PG 专有
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（SQLite 下直接语法错误）。
   改为**先 inspector 判列再加列**（与 ai04rag 同款幂等写法），
   PG / SQLite 都能跑，并挂回主链，使 `alembic upgrade head` 可用。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "sent01"
down_revision = "fe05b_frontend_logs"
branch_labels = None
depends_on = None

_TABLE = "sentiment_records"
# 与 backend/core/models.py 的 SentimentRecord 保持一致
_COLUMNS = (
    ("retail_heat_change_pct", sa.Float()),
    ("retail_heat_total", sa.Integer()),
)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _TABLE not in inspector.get_table_names():
        return  # 表尚不存在（create_all 会建），本次无需加列

    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _TABLE not in inspector.get_table_names():
        return

    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column(_TABLE, name)
