"""
BT-02 · 回测报告 API

POST /api/v1/backtest/reports — 持久化报告（绑定可复现性指纹）
GET  /api/v1/backtest/reports/{run_id} — 按 run_id 取回
GET  /api/v1/backtest/reports — 按 reproducibility_key / code_hash 查询
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.datalake_models import DataSnapshot
from backend.engine.contracts import RunManifest
from backend.services.backtest_report_service import BacktestReportService
from backend.services.datalake.manifest import build_manifest
from backend.services.datalake.snapshot_resolver import SnapshotResolveError, SnapshotResolver

router = APIRouter(prefix="/backtest", tags=["Backtest Reports"])


class RunManifestIn(BaseModel):
    run_id: str
    mode: str = "backtest"
    code_hash: str
    params: Dict[str, Any] = Field(default_factory=dict)
    data_snapshot_id: Optional[str] = None
    manifest_hash: Optional[str] = None
    random_seed: Optional[int] = None
    engine_version: str = "1.0.0"
    data_mode: str = "unbound"
    reproducible: bool = False


class PersistReportRequest(BaseModel):
    manifest: RunManifestIn
    metrics: Dict[str, Any]
    equity_curve: Optional[List[Dict[str, Any]]] = None
    trades: Optional[List[Dict[str, Any]]] = None
    symbol: Optional[str] = None
    notes: Optional[str] = None
    resolve_snapshot: bool = Field(
        default=True,
        description="若 manifest 缺 manifest_hash，尝试从 data_snapshot_id 解析",
    )


class RegisterSnapshotRequest(BaseModel):
    """测试/运维：注册一条 published 快照（正式发布走 DQ-03b）。"""

    snapshot_id: str
    as_of_date: str
    files: List[Dict[str, Any]] = Field(default_factory=list)
    ticker_count: Optional[int] = None


def _ok(data: Any, message: str = "ok") -> Dict[str, Any]:
    return {
        "status": "success",
        "message": message,
        "data": data,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _err(message: str, code: str = "BACKTEST_REPORT_ERROR") -> Dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "error_code": code,
        "data": None,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@router.post("/reports")
async def persist_backtest_report(req: PersistReportRequest, db: Session = Depends(get_db)):
    """持久化回测报告，绑定 code_hash + manifest_hash + params + seed。"""
    m = req.manifest
    data_mode = m.data_mode
    manifest_hash = m.manifest_hash
    snapshot_id = m.data_snapshot_id

    if req.resolve_snapshot and not manifest_hash:
        try:
            ref = SnapshotResolver(db).resolve(snapshot_id, manifest_hash=None)
            snapshot_id = ref.snapshot_id
            manifest_hash = ref.manifest_hash or None
            data_mode = ref.data_mode
        except SnapshotResolveError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    manifest = RunManifest(
        run_id=m.run_id,
        mode=m.mode if m.mode in ("backtest", "paper", "live") else "backtest",  # type: ignore[arg-type]
        code_hash=m.code_hash,
        params=m.params,
        data_snapshot_id=snapshot_id,
        manifest_hash=manifest_hash,
        random_seed=m.random_seed,
        engine_version=m.engine_version,
        data_mode=data_mode if data_mode in ("snapshot", "live", "unbound") else "unbound",  # type: ignore[arg-type]
        reproducible=False,  # service 重算
    )

    svc = BacktestReportService(db)
    row = svc.save(
        manifest,
        metrics=req.metrics,
        equity_curve=req.equity_curve,
        trades=req.trades,
        symbol=req.symbol,
        notes=req.notes,
    )
    return _ok(svc.to_public_dict(row), "回测报告已持久化")


@router.get("/reports/{run_id}")
async def get_backtest_report(run_id: str, db: Session = Depends(get_db)):
    svc = BacktestReportService(db)
    row = svc.get(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"报告不存在: {run_id}")
    return _ok(svc.to_public_dict(row))


@router.get("/reports")
async def list_backtest_reports(
    reproducibility_key: Optional[str] = None,
    code_hash: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    from backend.core.datalake_models import BacktestReport

    q = db.query(BacktestReport)
    if reproducibility_key:
        q = q.filter(BacktestReport.reproducibility_key == reproducibility_key)
    if code_hash:
        q = q.filter(BacktestReport.code_hash == code_hash)
    rows = q.order_by(BacktestReport.created_at.desc()).limit(min(limit, 100)).all()
    svc = BacktestReportService(db)
    return _ok([svc.to_public_dict(r) for r in rows])


@router.post("/snapshots/register")
async def register_snapshot_for_tests(req: RegisterSnapshotRequest, db: Session = Depends(get_db)):
    """注册 published 快照元数据（供联调 / 单测；生产由 DQ-03b 写入）。"""
    manifest = build_manifest(
        snapshot_id=req.snapshot_id,
        as_of_date=req.as_of_date,
        files=req.files
        or [
            {
                "path": f"kline/K_DAY/{req.snapshot_id}.parquet",
                "sha256": "0" * 64,
                "rows": 100,
                "bytes": 1024,
                "time_min": req.as_of_date,
                "time_max": req.as_of_date,
            }
        ],
    )
    as_of = date.fromisoformat(req.as_of_date)
    row = DataSnapshot(
        snapshot_id=req.snapshot_id,
        as_of_date=as_of,
        status="published",
        manifest_hash=manifest["manifest_hash"],
        manifest_json=manifest,
        ticker_count=req.ticker_count or manifest.get("ticker_count"),
        total_bytes=manifest.get("total_bytes"),
        storage_tier="local",
        published_at=datetime.now(timezone.utc),
    )
    db.merge(row)
    db.commit()
    return _ok(
        {
            "snapshot_id": row.snapshot_id,
            "manifest_hash": row.manifest_hash,
            "status": row.status,
        },
        "快照已注册",
    )
