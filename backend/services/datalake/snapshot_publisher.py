"""
DQ-03b · SnapshotPublisher

live → hardlink/copy → snapshots/snap_YYYYMMDD + manifest + PG + Redis。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.core.datalake_models import DataSnapshot
from backend.services.datalake.manifest import build_manifest, compute_manifest_hash
from backend.services.datalake.paths import (
    DIRTY_RATE_MAX,
    KTYPES_V1,
    LIVE_ROOT,
    REDIS_BUILDING_KEY,
    REDIS_CREATE_LOCK_PREFIX,
    REDIS_LATEST_KEY,
    SNAPSHOTS_ROOT,
    ensure_roots,
)

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    snapshot_id: str
    status: str
    manifest_hash: Optional[str] = None
    message: str = ""
    copy_mode: str = "hardlink"  # hardlink | copy2 | mixed


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy2"


def _file_meta(rel_path: str, abs_path: Path) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "path": rel_path,
        "sha256": _sha256_file(abs_path),
        "bytes": abs_path.stat().st_size,
        "rows": 0,
        "time_min": None,
        "time_max": None,
    }
    try:
        df = pd.read_parquet(abs_path, columns=["time"] if True else None)
        # 兼容无 time 列
        if "time" in df.columns:
            t = pd.to_datetime(df["time"])
            meta["rows"] = int(len(df))
            meta["time_min"] = str(t.min().date()) if len(t) else None
            meta["time_max"] = str(t.max().date()) if len(t) else None
        else:
            meta["rows"] = int(len(df))
    except Exception:
        pass
    return meta


class SnapshotPublisher:
    """从 live 层发布日快照。"""

    def __init__(
        self,
        db: Session,
        *,
        live_root: Optional[Path] = None,
        snapshots_root: Optional[Path] = None,
        quality_gate_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        universe_exporter: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> None:
        self._db = db
        self._live = Path(live_root) if live_root else LIVE_ROOT
        self._snaps = Path(snapshots_root) if snapshots_root else SNAPSHOTS_ROOT
        self._quality_gate_fn = quality_gate_fn or self._default_quality_gate
        self._universe_exporter = universe_exporter

    @staticmethod
    def _default_quality_gate() -> Dict[str, Any]:
        """无监控实例时放行；可注入覆盖。"""
        return {
            "passed": True,
            "dirty_rate_max": DIRTY_RATE_MAX,
            "dirty_rate_observed": 0.0,
            "sources_checked": [],
        }

    async def create_daily_snapshot(
        self,
        as_of_date: date,
        *,
        force: bool = False,
    ) -> PublishResult:
        ensure_roots()
        snapshot_id = f"snap_{as_of_date.strftime('%Y%m%d')}"
        existing = (
            self._db.query(DataSnapshot).filter(DataSnapshot.snapshot_id == snapshot_id).first()
        )
        if existing and existing.status == "published" and not force:
            return PublishResult(
                snapshot_id=snapshot_id,
                status="published",
                manifest_hash=existing.manifest_hash,
                message="idempotent_skip",
            )

        lock_key = f"{REDIS_CREATE_LOCK_PREFIX}{as_of_date.strftime('%Y%m%d')}"
        try:
            from backend.core.redis_client import redis_client

            got = await redis_client.set(lock_key, "1", nx=True, ex=7200)
            if not got and not force:
                return PublishResult(snapshot_id=snapshot_id, status="building", message="lock_held")
            await redis_client.set(REDIS_BUILDING_KEY, snapshot_id, ex=7200)
        except Exception as e:
            logger.warning("snapshot_lock_redis_unavailable", extra={"error": str(e)})

        quality = self._quality_gate_fn()
        if not quality.get("passed", True):
            self._upsert_row(
                snapshot_id,
                as_of_date,
                status="failed",
                manifest={"quality_gate": quality, "snapshot_id": snapshot_id},
                manifest_hash="0" * 64,
            )
            return PublishResult(snapshot_id=snapshot_id, status="failed", message="quality_gate")

        dest = self._snaps / snapshot_id
        if dest.exists() and force:
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)

        files_meta: List[Dict[str, Any]] = []
        modes: List[str] = []
        for ktype in KTYPES_V1:
            src_dir = self._live / ktype
            if not src_dir.is_dir():
                continue
            for src in sorted(src_dir.glob("*.parquet")):
                rel = f"kline/{ktype}/{src.name}"
                dst = dest / rel
                mode = _link_or_copy(src, dst)
                modes.append(mode)
                files_meta.append(_file_meta(rel, dst))

        sidecars: Dict[str, Any] = {"universe": None, "pit_store": None}
        sidecar_dir = dest / "sidecars"
        sidecar_dir.mkdir(exist_ok=True)
        if self._universe_exporter:
            try:
                uni = self._universe_exporter(sidecar_dir / "universe.json")
                sidecars["universe"] = uni
            except Exception as e:
                logger.warning("universe_sidecar_failed", extra={"error": str(e)})

        copy_mode = "hardlink"
        if modes and all(m == "copy2" for m in modes):
            copy_mode = "copy2"
        elif modes and any(m == "copy2" for m in modes):
            copy_mode = "mixed"

        manifest = build_manifest(
            snapshot_id=snapshot_id,
            as_of_date=as_of_date.isoformat(),
            files=files_meta,
            sidecars=sidecars,
            ktypes_included=list(KTYPES_V1),
            status="published",
            quality_gate=quality,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            source_sync_lock=f"quant:lock:kline_sync:{as_of_date.strftime('%Y%m%d')}",
        )
        manifest["copy_mode"] = copy_mode
        manifest["manifest_hash"] = compute_manifest_hash(manifest)
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # 只读保护（尽力而为；部分 FS 忽略）
        try:
            for p in dest.rglob("*"):
                if p.is_file():
                    os.chmod(p, 0o444)
        except OSError:
            pass

        self._upsert_row(
            snapshot_id,
            as_of_date,
            status="published",
            manifest=manifest,
            manifest_hash=manifest["manifest_hash"],
            ticker_count=manifest.get("ticker_count"),
            total_bytes=manifest.get("total_bytes"),
        )

        try:
            from backend.core.redis_client import redis_client

            await redis_client.set(REDIS_LATEST_KEY, snapshot_id)
            await redis_client.delete(REDIS_BUILDING_KEY)
        except Exception:
            pass

        try:
            from backend.core.metrics import DATALAKE_SNAPSHOT_CREATED

            DATALAKE_SNAPSHOT_CREATED.labels(status="published").inc()
        except Exception:
            pass

        logger.info(
            "snapshot_published",
            extra={"snapshot_id": snapshot_id, "files": len(files_meta), "mode": copy_mode},
        )
        return PublishResult(
            snapshot_id=snapshot_id,
            status="published",
            manifest_hash=manifest["manifest_hash"],
            message="ok",
            copy_mode=copy_mode,
        )

    def _upsert_row(
        self,
        snapshot_id: str,
        as_of_date: date,
        *,
        status: str,
        manifest: Dict[str, Any],
        manifest_hash: str,
        ticker_count: Optional[int] = None,
        total_bytes: Optional[int] = None,
    ) -> None:
        row = DataSnapshot(
            snapshot_id=snapshot_id,
            as_of_date=as_of_date,
            status=status,
            manifest_hash=manifest_hash,
            manifest_json=manifest,
            ticker_count=ticker_count,
            total_bytes=total_bytes,
            storage_tier="local",
            published_at=datetime.now(timezone.utc) if status == "published" else None,
        )
        self._db.merge(row)
        self._db.commit()


def default_universe_exporter(path: Path) -> Dict[str, Any]:
    """导出 DQ-01 universe sidecar（无 tracker 时写空包）。"""
    payload: Dict[str, Any] = {
        "symbols": [],
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from backend.services.survivorship_bias import SurvivorshipBiasTracker

        tracker = getattr(SurvivorshipBiasTracker, "_instance", None)
        if tracker is None:
            tracker = SurvivorshipBiasTracker()
        if hasattr(tracker, "export_snapshot"):
            payload = tracker.export_snapshot()
    except Exception:
        pass

    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": "sidecars/universe.json",
        "sha256": digest,
        "symbol_count": len(payload.get("symbols", [])),
    }
