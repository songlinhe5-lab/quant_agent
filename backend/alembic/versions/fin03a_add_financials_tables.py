"""add financials tables (FIN-03)

Revision ID: fin03a
Revises: sent01
Create Date: 2026-08-31

双时间轴事实层：
  financial_facts —— 科目 × 期间 × 版本，唯一键 (entity, concept, period_start_key, period_end, unit)
  filings         —— 申报归档索引，唯一键 (entity_id, accession_no)

⚠️ period_start 允许 NULL（时点科目），但 PG 的 NULL 互不相等会让唯一约束失效，
   故用非空列 period_start_key（时点值写 ''）承载唯一键，两列必须同步写入。
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "fin03a"
down_revision = "sent01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("concept", sa.String(64), nullable=False),
        sa.Column("statement", sa.String(16), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_start_key", sa.String(10), nullable=False, server_default=""),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(8), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False, server_default=""),
        sa.Column("value_as_reported", sa.Float(), nullable=False),
        sa.Column("value_latest", sa.Float(), nullable=False),
        sa.Column("restated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("derived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("filed_as_reported", sa.Date(), nullable=False),
        sa.Column("filed_latest", sa.Date(), nullable=False),
        sa.Column("accession_no", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="sec"),
        sa.Column("source_tag", sa.String(128), nullable=False, server_default=""),
        sa.Column("check_failed", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "entity_id",
            "concept",
            "period_start_key",
            "period_end",
            "unit",
            name="uq_financial_fact",
        ),
    )
    op.create_index("idx_fin_fact_pit", "financial_facts", ["entity_id", "filed_as_reported"])
    op.create_index("idx_fin_fact_period", "financial_facts", ["entity_id", "concept", "period_end"])

    op.create_table(
        "filings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_id", sa.String(64), nullable=False),
        sa.Column("form_type", sa.String(16), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("filed_at", sa.Date(), nullable=False),
        sa.Column("accession_no", sa.String(64), nullable=False),
        sa.Column("doc_url", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(4), nullable=False, server_default="en"),
        sa.Column("rag_indexed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("entity_id", "accession_no", name="uq_filings_accn"),
    )
    op.create_index("idx_filings_entity", "filings", ["entity_id", "filed_at"])


def downgrade() -> None:
    op.drop_index("idx_filings_entity", table_name="filings")
    op.drop_table("filings")
    op.drop_index("idx_fin_fact_period", table_name="financial_facts")
    op.drop_index("idx_fin_fact_pit", table_name="financial_facts")
    op.drop_table("financial_facts")
