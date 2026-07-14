"""
DQ-03a/c · Snapshot 解析器

将 data_snapshot_id（含 latest_published / live）解析为可绑定的 SnapshotRef。
BT-02 用 manifest_hash 做数据指纹；完整 Parquet 读取留给 DQ-03c 后续补齐。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from backend.core.datalake_models import DataSnapshot


class SnapshotResolveError(ValueError):
    """快照无法解析（缺失 / live 禁止 / 未发布）"""


@dataclass(frozen=True)
class SnapshotRef:
    snapshot_id: str
    manifest_hash: str
    data_mode: str  # snapshot | live | unbound
    status: str


class SnapshotResolver:
    """从 PostgreSQL（或显式 hash）解析回测数据指纹。"""

    LIVE_ID = "live"
    LATEST = "latest_published"

    def __init__(self, db: Optional[Session] = None) -> None:
        self._db = db

    @staticmethod
    def allow_live_data() -> bool:
        return os.getenv("ENGINE_ALLOW_LIVE_DATA", "false").lower() == "true"

    def resolve(
        self,
        data_snapshot_id: Optional[str] = None,
        *,
        manifest_hash: Optional[str] = None,
    ) -> SnapshotRef:
        """解析快照引用。

        - None / latest_published → 最近 published 行
        - snap_YYYYMMDD → 指定 published 行
        - live → 仅 DEV（ENGINE_ALLOW_LIVE_DATA=true）；不可用于 BT-02 持久化指纹
        - 若传入 manifest_hash 且无库：构造 unbound/snapshot 合成引用（测试用）
        """
        sid = (data_snapshot_id or self.LATEST).strip()

        if sid == self.LIVE_ID:
            if not self.allow_live_data():
                raise SnapshotResolveError(
                    "data_snapshot_id=live 仅允许开发环境（ENGINE_ALLOW_LIVE_DATA=true）"
                )
            return SnapshotRef(
                snapshot_id=self.LIVE_ID,
                manifest_hash=manifest_hash or "",
                data_mode="live",
                status="live",
            )

        if self._db is not None:
            row = self._lookup(sid)
            if row is not None:
                return SnapshotRef(
                    snapshot_id=row.snapshot_id,
                    manifest_hash=row.manifest_hash,
                    data_mode="snapshot",
                    status=row.status,
                )
            if sid != self.LATEST:
                raise SnapshotResolveError(f"快照不存在或未发布: {sid}")

        # 无 DB / 无 published：允许显式 manifest_hash（单元测试 / 预绑定）
        if manifest_hash:
            return SnapshotRef(
                snapshot_id=sid if sid != self.LATEST else "snap_unbound",
                manifest_hash=manifest_hash,
                data_mode="snapshot",
                status="published",
            )

        return SnapshotRef(
            snapshot_id="unbound",
            manifest_hash="",
            data_mode="unbound",
            status="missing",
        )

    def _lookup(self, sid: str) -> Optional[DataSnapshot]:
        assert self._db is not None
        q = self._db.query(DataSnapshot).filter(DataSnapshot.status == "published")
        if sid == self.LATEST:
            return q.order_by(DataSnapshot.as_of_date.desc()).first()
        return q.filter(DataSnapshot.snapshot_id == sid).first()
