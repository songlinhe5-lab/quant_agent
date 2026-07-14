"""add RAG governance fields (AI-04)

Revision ID: ai04rag
Revises:
Create Date: 2026-07-08

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ai04rag"
down_revision = None  # Adjust based on latest migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 检查表是否存在 (兼容 SQLite 测试环境)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "webpage_knowledge_base" not in inspector.get_table_names():
        return

    existing_columns = [c["name"] for c in inspector.get_columns("webpage_knowledge_base")]

    if "category" not in existing_columns:
        op.add_column(
            "webpage_knowledge_base",
            sa.Column("category", sa.String(20), nullable=True),
        )
        op.create_index("ix_webpage_knowledge_base_category", "webpage_knowledge_base", ["category"])

    if "embedding_model_version" not in existing_columns:
        op.add_column(
            "webpage_knowledge_base",
            sa.Column("embedding_model_version", sa.String(50), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "webpage_knowledge_base" not in inspector.get_table_names():
        return

    existing_columns = [c["name"] for c in inspector.get_columns("webpage_knowledge_base")]

    if "embedding_model_version" in existing_columns:
        op.drop_column("webpage_knowledge_base", "embedding_model_version")
    if "category" in existing_columns:
        op.drop_index("ix_webpage_knowledge_base_category", table_name="webpage_knowledge_base")
        op.drop_column("webpage_knowledge_base", "category")
