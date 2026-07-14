"""数据湖路径约定（live vs snapshots）。"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_DATA = Path(__file__).resolve().parents[3] / "data"

LIVE_ROOT = Path(
    os.getenv("DATALAKE_LIVE_ROOT", str(_REPO_DATA / "kline_warehouse"))
).resolve()
SNAPSHOTS_ROOT = Path(
    os.getenv("DATALAKE_SNAPSHOTS_ROOT", str(_REPO_DATA / "snapshots"))
).resolve()

KTYPES_V1 = ("K_DAY", "K_60M")

REDIS_LATEST_KEY = "quant:datalake:latest_snapshot_id"
REDIS_BUILDING_KEY = "quant:datalake:snapshot_building"
REDIS_CREATE_LOCK_PREFIX = "quant:lock:snapshot_create:"
REDIS_RETENTION_LOCK = "quant:lock:snapshot_retention"

DIRTY_RATE_MAX = float(os.getenv("DATALAKE_DIRTY_RATE_MAX", "0.02"))


def snapshot_dir(snapshot_id: str) -> Path:
    return SNAPSHOTS_ROOT / snapshot_id


def ensure_roots() -> None:
    LIVE_ROOT.mkdir(parents=True, exist_ok=True)
    SNAPSHOTS_ROOT.mkdir(parents=True, exist_ok=True)


def ticker_to_filename(ticker: str) -> str:
    return f"{ticker.replace('.', '_').replace('/', '_')}.parquet"


def filename_to_ticker(name: str) -> str:
    stem = name.replace(".parquet", "")
    # US_AAPL → US.AAPL；HK_00700 → HK.00700
    if "_" in stem:
        market, rest = stem.split("_", 1)
        return f"{market}.{rest}"
    return stem
