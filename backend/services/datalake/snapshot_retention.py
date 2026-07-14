"""
DQ-03d · SnapshotRetention

T1 (0–90d): 全保留
T2 (91–365d): 仅月锚点
T3 (>365d): tar 归档（可选 R2）+ 删本地
"""

from __future__ import annotations

import logging
import shutil
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.core.datalake_models import DataSnapshot
from backend.services.datalake.paths import REDIS_RETENTION_LOCK, SNAPSHOTS_ROOT, ensure_roots

logger = logging.getLogger(__name__)

T1_DAYS = 90
T3_DAYS = 365


class SnapshotRetention:
    def __init__(
        self,
        db: Session,
        *,
        snapshots_root: Optional[Path] = None,
        r2_uploader: Optional[Callable[[Path, str], str]] = None,
    ) -> None:
        self._db = db
        self._root = Path(snapshots_root) if snapshots_root else SNAPSHOTS_ROOT
        self._r2_uploader = r2_uploader

    def mark_monthly_anchors(self, year: int, month: int) -> Optional[str]:
        """将该月最后一个 published 日快照标为月锚点。"""
        rows: List[DataSnapshot] = (
            self._db.query(DataSnapshot)
            .filter(
                DataSnapshot.status == "published",
                DataSnapshot.as_of_date >= date(year, month, 1),
                DataSnapshot.as_of_date
                < (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)),
            )
            .order_by(DataSnapshot.as_of_date.desc())
            .all()
        )
        if not rows:
            return None
        anchor = rows[0]
        for r in rows:
            r.is_monthly_anchor = r.snapshot_id == anchor.snapshot_id
        self._db.commit()
        return anchor.snapshot_id

    def run(self, as_of: Optional[date] = None) -> dict:
        """执行保留策略。返回动作摘要。"""
        ensure_roots()
        today = as_of or date.today()
        summary = {"deleted_local": [], "archived": [], "anchors": []}

        # 为本月与上月打锚点
        summary["anchors"].append(self.mark_monthly_anchors(today.year, today.month))
        prev = today.replace(day=1) - timedelta(days=1)
        summary["anchors"].append(self.mark_monthly_anchors(prev.year, prev.month))

        rows = (
            self._db.query(DataSnapshot)
            .filter(DataSnapshot.status == "published")
            .all()
        )
        for row in rows:
            age = (today - row.as_of_date).days
            if age <= T1_DAYS:
                continue
            if age <= T3_DAYS:
                # T2: 非锚点删除本地
                if not row.is_monthly_anchor and row.storage_tier == "local":
                    self._delete_local(row)
                    summary["deleted_local"].append(row.snapshot_id)
            else:
                # T3: 归档
                if row.storage_tier == "local":
                    key = self._archive(row)
                    summary["archived"].append({"id": row.snapshot_id, "r2_key": key})

        try:
            from backend.core.metrics import DATALAKE_RETENTION_RUNS

            DATALAKE_RETENTION_RUNS.inc()
        except Exception:
            pass

        return summary

    def _delete_local(self, row: DataSnapshot) -> None:
        d = self._root / row.snapshot_id
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
        row.storage_tier = "deleted"
        self._db.commit()
        logger.info("snapshot_local_deleted", extra={"snapshot_id": row.snapshot_id})

    def _archive(self, row: DataSnapshot) -> Optional[str]:
        src = self._root / row.snapshot_id
        archive_dir = self._root / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        tar_path = archive_dir / f"{row.snapshot_id}.tar.gz"

        if src.is_dir() and not tar_path.exists():
            with tarfile.open(tar_path, "w:gz") as tar:
                tar.add(src, arcname=row.snapshot_id)

        r2_key = None
        if self._r2_uploader and tar_path.exists():
            try:
                r2_key = self._r2_uploader(tar_path, f"quant-datalake/snapshots/{row.snapshot_id}.tar.gz")
            except Exception as e:
                logger.warning("r2_upload_failed", extra={"error": str(e)})

        if src.is_dir():
            shutil.rmtree(src, ignore_errors=True)

        row.storage_tier = "r2" if r2_key else "deleted"
        row.r2_key = r2_key or str(tar_path)
        row.archived_at = datetime.now(timezone.utc)
        self._db.commit()
        return row.r2_key


async def run_retention_with_lock(db: Session) -> Optional[dict]:
    """带 Redis 锁的保留任务入口。"""
    try:
        from backend.core.redis_client import redis_client

        got = await redis_client.set(REDIS_RETENTION_LOCK, "1", nx=True, ex=3600)
        if not got:
            return None
    except Exception:
        pass
    return SnapshotRetention(db).run()
