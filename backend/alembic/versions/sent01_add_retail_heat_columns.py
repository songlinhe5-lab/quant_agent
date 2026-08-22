"""add retail_heat columns to sentiment_records

C.1 热度因子接入研判层新增 retail_heat_change_pct / retail_heat_total 两列。
生产库为已存在的旧表（create_all 不会给已有表加列），需显式迁移。
幂等：PostgreSQL 15+ 支持 ADD COLUMN IF NOT EXISTS；down_revision=None 作为独立迁移。

Revision ID: sent01
Revises: (独立 head，不与历史链耦合，避免旧链混乱导致冲突)
Create Date: 2026-08-22
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "sent01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 幂等加列：PostgreSQL 15+ 支持 IF NOT EXISTS（若数据库曾部分迁移则不重复加）
    op.execute("ALTER TABLE sentiment_records ADD COLUMN IF NOT EXISTS retail_heat_change_pct DOUBLE PRECISION")
    op.execute("ALTER TABLE sentiment_records ADD COLUMN IF NOT EXISTS retail_heat_total INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE sentiment_records DROP COLUMN IF EXISTS retail_heat_total")
    op.execute("ALTER TABLE sentiment_records DROP COLUMN IF EXISTS retail_heat_change_pct")
