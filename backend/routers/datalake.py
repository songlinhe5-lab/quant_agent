"""
DQ-03e · 数据湖快照管理 API

GET  /api/v1/datalake/snapshots
GET  /api/v1/datalake/snapshots/latest
GET  /api/v1/datalake/snapshots/{snapshot_id}
POST /api/v1/datalake/snapshots/rebuild
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.datalake_models import DataSnapshot
from backend.services.datalake.snapshot_publisher import (
    SnapshotPublisher,
    default_universe_exporter,
)
from backend.services.datalake.snapshot_reader import SnapshotReader
from backend.services.datalake.snapshot_retention import SnapshotRetention

router = APIRouter(prefix="/datalake", tags=["Data Lake Snapshots"])


def _ok(data: Any, message: str = "ok") -> Dict[str, Any]:
    return {
        "status": "success",
        "message": message,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


class RebuildRequest(BaseModel):
    as_of_date: str = Field(..., description="YYYY-MM-DD")
    force: bool = False


def _row_to_dict(row: DataSnapshot) -> Dict[str, Any]:
    return {
        "snapshot_id": row.snapshot_id,
        "as_of_date": row.as_of_date.isoformat() if row.as_of_date else None,
        "status": row.status,
        "manifest_hash": row.manifest_hash,
        "ticker_count": row.ticker_count,
        "total_bytes": row.total_bytes,
        "is_monthly_anchor": row.is_monthly_anchor,
        "storage_tier": row.storage_tier,
        "r2_key": row.r2_key,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


@router.get("/snapshots")
async def list_snapshots(
    status: Optional[str] = Query(default="published"),
    storage_tier: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(DataSnapshot)
    if status:
        q = q.filter(DataSnapshot.status == status)
    if storage_tier:
        q = q.filter(DataSnapshot.storage_tier == storage_tier)
    rows = q.order_by(DataSnapshot.as_of_date.desc()).limit(limit).all()
    return _ok([_row_to_dict(r) for r in rows])


@router.get("/snapshots/latest")
async def latest_snapshot(db: Session = Depends(get_db)):
    row = (
        db.query(DataSnapshot)
        .filter(DataSnapshot.status == "published")
        .order_by(DataSnapshot.as_of_date.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="无 published 快照")
    age = (date.today() - row.as_of_date).days
    try:
        from backend.core.metrics import DATALAKE_LATEST_AGE_DAYS

        DATALAKE_LATEST_AGE_DAYS.set(age)
    except Exception:
        pass
    data = _row_to_dict(row)
    data["age_days"] = age
    data["stale_warning"] = age >= 3
    return _ok(data)


@router.get("/snapshots/{snapshot_id}")
async def get_snapshot(snapshot_id: str, db: Session = Depends(get_db)):
    row = db.query(DataSnapshot).filter(DataSnapshot.snapshot_id == snapshot_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"快照不存在: {snapshot_id}")
    reader = SnapshotReader(db)
    manifest = reader.get_manifest(snapshot_id) or row.manifest_json
    data = _row_to_dict(row)
    data["manifest"] = manifest
    return _ok(data)


@router.post("/snapshots/rebuild")
async def rebuild_snapshot(req: RebuildRequest, db: Session = Depends(get_db)):
    as_of = date.fromisoformat(req.as_of_date)
    publisher = SnapshotPublisher(
        db,
        universe_exporter=default_universe_exporter,
    )
    result = await publisher.create_daily_snapshot(as_of, force=req.force)
    if result.status == "failed":
        raise HTTPException(status_code=422, detail=result.message)
    return _ok(
        {
            "snapshot_id": result.snapshot_id,
            "status": result.status,
            "manifest_hash": result.manifest_hash,
            "copy_mode": result.copy_mode,
            "message": result.message,
        },
        "快照已生成",
    )


@router.post("/snapshots/retention/run")
async def run_retention(db: Session = Depends(get_db)):
    summary = SnapshotRetention(db).run()
    return _ok(summary, "保留策略已执行")
