"""
FIN-03 · 财报宽表（Parquet，接 docs/19 快照）
=============================================

多期报表与截面面板走 Parquet，供因子与回测按 `data_snapshot_id` 整包读取，
避免每次分析都回查 PG。目录约定复用 `datalake/paths`：

    <SNAPSHOTS_ROOT>/<snapshot_id>/financials/<entity>/<statement>.parquet
    <SNAPSHOTS_ROOT>/<snapshot_id>/financials/<entity>/<statement>.meta.json

宽表形状：行 = 标准科目（concept），列 = 期间标签（FY2025 / FY2025 Q1 …）。
口径（as_reported / latest）与来源分布写在 meta 里——口径不可见即不可信。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from backend.services.datalake import paths

SUBDIR = "financials"


def _safe_entity(entity_id: str) -> str:
    """US:CIK0000320193 → US_CIK0000320193（Windows 与对象存储都不吃冒号）"""
    return entity_id.replace(":", "_").replace("/", "_")


def table_dir(entity_id: str, snapshot_id: str) -> Path:
    return paths.snapshot_dir(snapshot_id) / SUBDIR / _safe_entity(entity_id)


def write_wide_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    entity_id: str,
    statement: str,
    snapshot_id: str,
    basis: str,
    currency: str,
    source_mix: Mapping[str, int] | None = None,
) -> Path:
    """写宽表 + meta。rows: [{"concept": "revenue", "values": {"FY2025": 1.0, ...}}]"""
    frame = pd.DataFrame([{"concept": row["concept"], **dict(row.get("values") or {})} for row in rows]).set_index(
        "concept"
    )
    frame = frame.sort_index()

    directory = table_dir(entity_id, snapshot_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{statement}.parquet"
    frame.to_parquet(path)

    meta = {
        "entity_id": entity_id,
        "statement": statement,
        "snapshot_id": snapshot_id,
        "basis": basis,  # as_reported | latest
        "currency": currency,
        "source_mix": dict(source_mix or {}),
        "rows": int(frame.shape[0]),
        "periods": list(frame.columns),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    (directory / f"{statement}.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return path


def read_wide_table(entity_id: str, statement: str, snapshot_id: str) -> pd.DataFrame:
    """读宽表（index = concept）。文件不存在由调用方判空，不隐式造空表。"""
    return pd.read_parquet(table_dir(entity_id, snapshot_id) / f"{statement}.parquet")


def read_meta(entity_id: str, statement: str, snapshot_id: str) -> dict[str, Any]:
    payload = (table_dir(entity_id, snapshot_id) / f"{statement}.meta.json").read_text(encoding="utf-8")
    meta: dict[str, Any] = json.loads(payload)
    return meta
