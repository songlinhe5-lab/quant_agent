"""add_frontend_logs_table

Revision ID: fe05b_frontend_logs
Revises: strat03a_add_strategy_version_tables
Create Date: 2026-07-14

FE-05b: 前端日志采集表
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fe05b_frontend_logs"
down_revision: Union[str, None] = "strat03a_add_strategy_version_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "frontend_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=2048), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("page_url", sa.String(length=512), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_frontend_logs_id"), "frontend_logs", ["id"], unique=False)
    op.create_index(op.f("ix_frontend_logs_timestamp"), "frontend_logs", ["timestamp"], unique=False)
    op.create_index(op.f("ix_frontend_logs_level"), "frontend_logs", ["level"], unique=False)
    op.create_index(op.f("ix_frontend_logs_user_id"), "frontend_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_frontend_logs_user_id"), table_name="frontend_logs")
    op.drop_index(op.f("ix_frontend_logs_level"), table_name="frontend_logs")
    op.drop_index(op.f("ix_frontend_logs_timestamp"), table_name="frontend_logs")
    op.drop_index(op.f("ix_frontend_logs_id"), table_name="frontend_logs")
    op.drop_table("frontend_logs")
