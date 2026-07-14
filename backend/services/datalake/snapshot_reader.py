"""
DQ-03a/c · SnapshotReader — 回测只读访问快照目录

读 data/snapshots/snap_YYYYMMDD/kline/{ktype}/{ticker}.parquet
snapshot_id=latest_published 时经 Redis / PG 解析。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from sqlalchemy.orm import Session

from backend.services.datalake.paths import (
    REDIS_LATEST_KEY,
    SNAPSHOTS_ROOT,
    filename_to_ticker,
    ticker_to_filename,
)
from backend.services.datalake.snapshot_resolver import SnapshotResolveError, SnapshotResolver

logger = logging.getLogger(__name__)


class SnapshotReader:
    """快照只读访问（V1 仅 storage_tier=local）。"""

    def __init__(
        self,
        db: Optional[Session] = None,
        snapshots_root: Optional[Path] = None,
    ) -> None:
        self._db = db
        self._root = Path(snapshots_root) if snapshots_root else SNAPSHOTS_ROOT
        self._resolver = SnapshotResolver(db)

    async def resolve_snapshot_id(self, snapshot_id: Optional[str]) -> str:
        """解析 latest_published → 具体 snap_id。"""
        sid = (snapshot_id or "latest_published").strip()
        if sid == "live":
            return "live"

        # Redis 指针优先
        if sid == "latest_published":
            try:
                from backend.core.redis_client import redis_client

                cached = await redis_client.get(REDIS_LATEST_KEY)
                if cached:
                    return cached if isinstance(cached, str) else cached.decode()
            except Exception:
                pass

        ref = self._resolver.resolve(sid)
        if ref.data_mode == "unbound" or ref.status == "missing":
            raise SnapshotResolveError("无可用 published 快照（latest_published 为空）")
        if ref.data_mode == "live":
            return "live"
        return ref.snapshot_id

    def get_manifest(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        path = self._root / snapshot_id / "manifest.json"
        if not path.is_file():
            if self._db is not None:
                from backend.core.datalake_models import DataSnapshot

                row = self._db.query(DataSnapshot).filter(DataSnapshot.snapshot_id == snapshot_id).first()
                if row:
                    return dict(row.manifest_json)
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def get_history_sync(
        self,
        snapshot_id: str,
        ticker: str,
        ktype: str = "K_DAY",
        num: int = 252,
    ) -> Optional[pd.DataFrame]:
        """同步读取快照 K 线。live / 缺失返回 None。"""
        if snapshot_id in ("live", "unbound", "latest_published"):
            return None

        file_path = self._root / snapshot_id / "kline" / ktype / ticker_to_filename(ticker)
        if not file_path.is_file():
            # 兼容文件名已是安全名
            alt = self._root / snapshot_id / "kline" / ktype / f"{ticker}.parquet"
            file_path = alt if alt.is_file() else file_path
        if not file_path.is_file():
            logger.debug("snapshot_file_missing", extra={"path": str(file_path)})
            return None

        df = pd.read_parquet(file_path)
        if "time" in df.columns:
            df = df.sort_values("time")
        return df.tail(num).copy()

    async def get_history(
        self,
        snapshot_id: str,
        ticker: str,
        ktype: str = "K_DAY",
        num: int = 252,
    ) -> Optional[pd.DataFrame]:
        resolved = await self.resolve_snapshot_id(snapshot_id)
        if resolved == "live":
            return None
        return await asyncio.to_thread(self.get_history_sync, resolved, ticker, ktype, num)

    def list_tickers(self, snapshot_id: str, ktype: str = "K_DAY") -> list[str]:
        d = self._root / snapshot_id / "kline" / ktype
        if not d.is_dir():
            return []
        return [filename_to_ticker(p.name) for p in d.glob("*.parquet")]
