"""
FIN-03: 财报宽表（parquet_store）— 单元测试
===========================================

验证:
  1. 宽表形状（行=科目、列=期间）与 round-trip
  2. meta 必须带口径 / 货币 / 来源分布（口径不可见即不可信）
  3. 落盘路径接 docs/19 快照目录，entity_id 的冒号须转义

用 tmp 快照根目录，不打真实 PG/Redis/外网。
"""

import pytest

from backend.services.datalake import paths
from backend.services.financials import parquet_store

ROWS = [
    {"concept": "revenue", "values": {"FY2023": 383.3, "FY2024": 391.0, "FY2025": 416.2}},
    {"concept": "net_income", "values": {"FY2023": 97.0, "FY2024": 93.7, "FY2025": 112.0}},
    {"concept": "cfo", "values": {"FY2023": 110.5, "FY2024": 118.3, "FY2025": 118.0}},
]


@pytest.fixture
def snapshot_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "SNAPSHOTS_ROOT", tmp_path)
    return tmp_path


def test_write_and_read_round_trip(snapshot_root):
    path = parquet_store.write_wide_table(
        ROWS,
        entity_id="US:CIK0000320193",
        statement="income",
        snapshot_id="snap_20260831",
        basis="as_reported",
        currency="USD",
        source_mix={"sec": 9},
    )
    assert path.exists()

    frame = parquet_store.read_wide_table("US:CIK0000320193", "income", "snap_20260831")
    assert list(frame.columns) == ["FY2023", "FY2024", "FY2025"]
    assert list(frame.index) == ["cfo", "net_income", "revenue"]  # 按科目排序
    assert frame.loc["revenue", "FY2025"] == 416.2


def test_meta_carries_basis_currency_and_source_mix(snapshot_root):
    parquet_store.write_wide_table(
        ROWS,
        entity_id="US:CIK0000320193",
        statement="income",
        snapshot_id="snap_20260831",
        basis="latest",
        currency="USD",
        source_mix={"sec": 8, "futu": 1},
    )
    meta = parquet_store.read_meta("US:CIK0000320193", "income", "snap_20260831")

    assert meta["basis"] == "latest"
    assert meta["currency"] == "USD"
    assert meta["source_mix"] == {"sec": 8, "futu": 1}
    assert meta["rows"] == 3
    assert meta["periods"] == ["FY2023", "FY2024", "FY2025"]
    assert meta["snapshot_id"] == "snap_20260831"


def test_tables_land_under_snapshot_dir_and_escape_colon(snapshot_root):
    parquet_store.write_wide_table(
        ROWS,
        entity_id="US:CIK0000320193",
        statement="balance",
        snapshot_id="snap_20260831",
        basis="latest",
        currency="USD",
    )
    target = snapshot_root / "snap_20260831" / "financials" / "US_CIK0000320193" / "balance.parquet"
    assert target.exists()
    assert parquet_store.table_dir("US:CIK0000320193", "snap_20260831").name == "US_CIK0000320193"


def test_read_missing_table_raises_instead_of_returning_empty(snapshot_root):
    with pytest.raises(FileNotFoundError):
        parquet_store.read_wide_table("US:CIK0000320193", "cash", "snap_missing")
