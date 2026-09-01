"""add financial_jobs table (FIN-10)

Revision ID: fin10a
Revises: fin03a
Create Date: 2026-09-01

回填任务登记簿持久化：内存 jobs（重启即失）的 PG 快照，主键 job_id；
写侧 best-effort 双写，读侧内存优先、miss 落库。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "fin10a"
down_revision = "fin03a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_jobs",
        sa.Column("job_id", sa.String(32), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="sec"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_index("idx_fin_jobs_entity", "financial_jobs", ["entity_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_fin_jobs_entity", table_name="financial_jobs")
    op.drop_table("financial_jobs")
