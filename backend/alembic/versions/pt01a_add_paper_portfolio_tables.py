"""add paper portfolio tables

Revision ID: pt01a
Revises: strat03a
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "pt01a"
down_revision = "strat03a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # paper_portfolios: 组合主档
    op.create_table(
        "paper_portfolios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("strategy_name", sa.String(64), index=True, nullable=False),
        sa.Column("strategy_version_id", sa.String(64), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("initial_capital", sa.Float(), default=100000.0),
        sa.Column("benchmark_backtest_ref", sa.String(64), nullable=True),
        sa.Column("bot_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(12), default="running"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # paper_fills: 成交流水（只增，账本 SSOT）
    op.create_table(
        "paper_fills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("paper_portfolios.id"), index=True, nullable=False),
        sa.Column("fill_seq", sa.BigInteger(), nullable=False),
        sa.Column("dt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("commission", sa.Float(), default=0.0),
        sa.Column("slippage", sa.Float(), default=0.0),
        sa.Column("intent_tag", sa.String(64), nullable=True),
    )
    op.create_index(
        "idx_paper_fill_unique_seq",
        "paper_fills",
        ["portfolio_id", "fill_seq"],
        unique=True,
    )

    # paper_positions: 持仓现状（投影，可重建）
    op.create_table(
        "paper_positions",
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("paper_portfolios.id"), primary_key=True),
        sa.Column("symbol", sa.String(32), primary_key=True),
        sa.Column("qty", sa.Integer(), default=0),
        sa.Column("avg_cost", sa.Float(), default=0.0),
        sa.Column("last_fill_seq", sa.BigInteger(), default=0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # paper_nav_daily: 日终净值（不可变）
    op.create_table(
        "paper_nav_daily",
        sa.Column("portfolio_id", sa.String(36), sa.ForeignKey("paper_portfolios.id"), primary_key=True),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("nav", sa.Float(), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("market_value", sa.Float(), nullable=False),
        sa.Column("daily_return", sa.Float(), nullable=True),
        sa.Column("stale_symbols", sa.JSON(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("paper_nav_daily")
    op.drop_table("paper_positions")
    op.drop_table("paper_fills")
    op.drop_table("paper_portfolios")
