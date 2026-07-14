"""
DQ-03a / BT-02 · 数据快照与回测报告 ORM

data_snapshots: 不可变快照元数据（manifest_hash 为数据指纹）
backtest_reports: 回测可复现性绑定 + 指标持久化
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.core.database import Base


class DataSnapshot(Base):
    """Parquet 数据湖日快照元数据（docs/19 §四）"""

    __tablename__ = "data_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="building", index=True)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    ticker_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_monthly_anchor: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_tier: Mapped[str] = mapped_column(String(8), default="local")
    r2_key: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_data_snapshots_published", "status", "published_at"),)


class BacktestReport(Base):
    """回测报告持久化（BT-02 · docs/19 §四 / docs/15 RunManifest）"""

    __tablename__ = "backtest_reports"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data_snapshot_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("data_snapshots.snapshot_id"),
        nullable=True,
        index=True,
    )
    manifest_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    params: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    random_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    engine_version: Mapped[str] = mapped_column(String(32), default="1.0.0")
    data_mode: Mapped[str] = mapped_column(String(16), default="unbound")
    reproducible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reproducibility_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    metrics: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    equity_curve: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    trades: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    result_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (Index("idx_backtest_reports_repro_key", "reproducibility_key"),)
