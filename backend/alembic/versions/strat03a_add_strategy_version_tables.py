"""add strategy version tables

Revision ID: strat03a
Revises:
Create Date: 2025-01-13

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "strat03a"
down_revision = None  # Adjust based on latest migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create strategies table
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("head_version_id", sa.String(64), nullable=True),
        sa.Column("deployed_version_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_archived", sa.Boolean(), default=False),
    )

    # Create strategy_versions table
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("strategy_id", sa.String(64), sa.ForeignKey("strategies.id"), index=True),
        sa.Column("seq", sa.Integer(), index=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.String(64), index=True),
        sa.Column("params_schema", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(32), index=True),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create unique index for idempotency
    op.create_index("idx_strategy_version_unique_hash", "strategy_versions", ["strategy_id", "code_hash"], unique=True)

    # Create index for version sequence
    op.create_index("idx_strategy_version_seq", "strategy_versions", ["strategy_id", "seq"])


def downgrade() -> None:
    op.drop_table("strategy_versions")
    op.drop_table("strategies")
