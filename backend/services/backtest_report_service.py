"""
BT-02 · 回测报告持久化与可复现性指纹

绑定：code_hash + manifest_hash + params + random_seed
同输入必得同输出：result_digest 契约测试
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.core.datalake_models import BacktestReport
from backend.engine.contracts import RunManifest
from backend.services.datalake.manifest import canonical_json


def compute_reproducibility_key(
    code_hash: str,
    manifest_hash: str,
    params: Dict[str, Any],
    random_seed: Optional[int],
) -> str:
    """可复现性输入指纹（不含 run_id / 时间戳）。"""
    payload = {
        "code_hash": code_hash,
        "manifest_hash": manifest_hash,
        "params": params or {},
        "random_seed": random_seed,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_result_digest(
    metrics: Dict[str, Any],
    equity_curve: List[Dict[str, Any]],
) -> str:
    """结果指纹：用于断言同输入同输出。"""
    # 权益曲线只取 equity，避免日期格式噪声
    curve = [{"equity": e.get("equity")} for e in (equity_curve or [])]
    payload = {"metrics": metrics or {}, "equity": curve}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def is_reproducible(
    *,
    code_hash: str,
    manifest_hash: Optional[str],
    random_seed: Optional[int],
    data_mode: str,
) -> bool:
    """正式可复现：快照模式 + 非空数据指纹 + 固定种子 + 非空代码 hash。"""
    return data_mode == "snapshot" and bool(code_hash) and bool(manifest_hash) and random_seed is not None


class BacktestReportService:
    """回测报告 CRUD（PostgreSQL / SQLite）。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    def save(
        self,
        manifest: RunManifest,
        *,
        metrics: Dict[str, Any],
        equity_curve: Optional[List[Dict[str, Any]]] = None,
        trades: Optional[List[Dict[str, Any]]] = None,
        symbol: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> BacktestReport:
        """持久化报告。live / unbound 允许落库但 reproducible=false。"""
        data_mode = getattr(manifest, "data_mode", "unbound") or "unbound"
        manifest_hash = getattr(manifest, "manifest_hash", None) or None
        reproducible = is_reproducible(
            code_hash=manifest.code_hash,
            manifest_hash=manifest_hash,
            random_seed=manifest.random_seed,
            data_mode=data_mode,
        )
        if data_mode == "live":
            # docs/19：禁止用 live 作为 BT-02 可复现持久化指纹
            reproducible = False
            snapshot_fk = None
        else:
            sid = manifest.data_snapshot_id
            snapshot_fk = None
            if sid and str(sid).startswith("snap_") and sid not in ("snap_live", "snap_unbound"):
                from backend.core.datalake_models import DataSnapshot

                exists = self._db.query(DataSnapshot.snapshot_id).filter(DataSnapshot.snapshot_id == sid).first()
                if exists:
                    snapshot_fk = sid

        repro_key = None
        if reproducible and manifest_hash:
            repro_key = compute_reproducibility_key(
                manifest.code_hash,
                manifest_hash,
                manifest.params,
                manifest.random_seed,
            )

        digest = compute_result_digest(metrics, equity_curve or [])

        row = BacktestReport(
            run_id=manifest.run_id,
            data_snapshot_id=snapshot_fk,
            manifest_hash=manifest_hash,
            code_hash=manifest.code_hash,
            params=manifest.params or {},
            random_seed=manifest.random_seed,
            engine_version=manifest.engine_version,
            data_mode=data_mode,
            reproducible=reproducible,
            reproducibility_key=repro_key,
            metrics=metrics,
            equity_curve=equity_curve,
            trades=trades,
            result_digest=digest,
            symbol=symbol,
            notes=notes,
        )
        merged = self._db.merge(row)
        self._db.commit()
        self._db.refresh(merged)
        return merged

    def get(self, run_id: str) -> Optional[BacktestReport]:
        return self._db.query(BacktestReport).filter(BacktestReport.run_id == run_id).first()

    def find_by_reproducibility_key(self, key: str) -> List[BacktestReport]:
        return (
            self._db.query(BacktestReport)
            .filter(BacktestReport.reproducibility_key == key)
            .order_by(BacktestReport.created_at.desc())
            .all()
        )

    def to_public_dict(self, row: BacktestReport) -> Dict[str, Any]:
        return {
            "run_id": row.run_id,
            "data_snapshot_id": row.data_snapshot_id,
            "manifest_hash": row.manifest_hash,
            "code_hash": row.code_hash,
            "params": row.params,
            "random_seed": row.random_seed,
            "engine_version": row.engine_version,
            "data_mode": row.data_mode,
            "reproducible": row.reproducible,
            "reproducibility_key": row.reproducibility_key,
            "metrics": row.metrics,
            "equity_curve": row.equity_curve,
            "trades": row.trades,
            "result_digest": row.result_digest,
            "symbol": row.symbol,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "badge": {
                "code_hash": (row.code_hash or "")[:12],
                "manifest_hash": (row.manifest_hash or "")[:12] if row.manifest_hash else None,
                "reproducible": row.reproducible,
            },
        }
