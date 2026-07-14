"""
DQ-03 · 数据湖快照版本化测试

覆盖：publisher 幂等/质量门禁、reader、retention 锚点与删除、路由。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.core.datalake_models import DataSnapshot
from backend.services.datalake.manifest import validate_manifest
from backend.services.datalake.snapshot_publisher import SnapshotPublisher
from backend.services.datalake.snapshot_reader import SnapshotReader
from backend.services.datalake.snapshot_retention import SnapshotRetention


@pytest.fixture()
def tmp_lake(tmp_path: Path):
    live = tmp_path / "live"
    snaps = tmp_path / "snaps"
    (live / "K_DAY").mkdir(parents=True)
    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=30, freq="D"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1e6,
        }
    )
    df.to_parquet(live / "K_DAY" / "US_AAPL.parquet", index=False)
    return live, snaps


@pytest.fixture()
def db_session():
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


@pytest.mark.asyncio
async def test_publisher_creates_published_snapshot(tmp_lake, db_session):
    live, snaps = tmp_lake
    pub = SnapshotPublisher(
        db_session,
        live_root=live,
        snapshots_root=snaps,
        quality_gate_fn=lambda: {"passed": True, "dirty_rate_max": 0.02, "sources_checked": []},
        universe_exporter=lambda p: (
            p.write_text('{"symbols":["US.AAPL"]}'),
            {"path": "sidecars/universe.json", "sha256": "abc", "symbol_count": 1},
        )[1],
    )
    result = await pub.create_daily_snapshot(date(2026, 7, 13))
    assert result.status == "published"
    assert result.manifest_hash
    assert (snaps / "snap_20260713" / "manifest.json").is_file()
    assert (snaps / "snap_20260713" / "kline" / "K_DAY" / "US_AAPL.parquet").is_file()

    row = db_session.query(DataSnapshot).filter_by(snapshot_id="snap_20260713").one()
    assert row.status == "published"
    assert validate_manifest(row.manifest_json)

    # 幂等
    again = await pub.create_daily_snapshot(date(2026, 7, 13))
    assert again.message == "idempotent_skip"


@pytest.mark.asyncio
async def test_publisher_quality_gate_blocks(tmp_lake, db_session):
    live, snaps = tmp_lake
    pub = SnapshotPublisher(
        db_session,
        live_root=live,
        snapshots_root=snaps,
        quality_gate_fn=lambda: {"passed": False, "dirty_rate_max": 0.02, "dirty_rate_observed": 0.5},
    )
    result = await pub.create_daily_snapshot(date(2026, 7, 14), force=True)
    assert result.status == "failed"
    row = db_session.query(DataSnapshot).filter_by(snapshot_id="snap_20260714").one()
    assert row.status == "failed"


@pytest.mark.asyncio
async def test_reader_get_history(tmp_lake, db_session):
    live, snaps = tmp_lake
    pub = SnapshotPublisher(
        db_session,
        live_root=live,
        snapshots_root=snaps,
        quality_gate_fn=lambda: {"passed": True, "dirty_rate_max": 0.02, "sources_checked": []},
    )
    await pub.create_daily_snapshot(date(2026, 7, 13))

    reader = SnapshotReader(db_session, snapshots_root=snaps)
    df = await reader.get_history("snap_20260713", "US.AAPL", "K_DAY", num=10)
    assert df is not None
    assert len(df) == 10

    # 同 snapshot 两次一致
    df2 = await reader.get_history("snap_20260713", "US.AAPL", "K_DAY", num=10)
    assert list(df["close"]) == list(df2["close"])


def test_retention_marks_anchor_and_deletes_t2(tmp_lake, db_session):
    live, snaps = tmp_lake
    # 造 3 个 published 行：老非锚点应被删
    for d, anchor in [
        (date(2025, 1, 10), False),
        (date(2025, 1, 31), True),
        (date(2026, 6, 1), False),
    ]:
        sid = f"snap_{d.strftime('%Y%m%d')}"
        (snaps / sid / "kline" / "K_DAY").mkdir(parents=True)
        (snaps / sid / "dummy.txt").write_text("x")
        db_session.add(
            DataSnapshot(
                snapshot_id=sid,
                as_of_date=d,
                status="published",
                manifest_hash="a" * 64,
                manifest_json={"snapshot_id": sid},
                is_monthly_anchor=anchor,
                storage_tier="local",
                published_at=datetime.now(timezone.utc),
            )
        )
    db_session.commit()

    today = date(2026, 7, 13)
    # age of 2025-01-10 ≈ 549 days > 365 → T3 archive
    # age of 2025-01-31 similarly T3
    # 2026-06-01 age ≈ 42 days → T1 keep
    ret = SnapshotRetention(db_session, snapshots_root=snaps)
    summary = ret.run(as_of=today)
    assert "snap_20250110" in [a["id"] for a in summary["archived"]] or (
        db_session.query(DataSnapshot).filter_by(snapshot_id="snap_20250110").one().storage_tier in ("r2", "deleted")
    )


def test_retention_t2_deletes_non_anchor(tmp_path, db_session):
    snaps = tmp_path / "snaps"
    # 120 天前非锚点 → T2 删除
    d = date.today() - __import__("datetime").timedelta(days=120)
    sid = f"snap_{d.strftime('%Y%m%d')}"
    (snaps / sid).mkdir(parents=True)
    (snaps / sid / "f.txt").write_text("1")
    db_session.add(
        DataSnapshot(
            snapshot_id=sid,
            as_of_date=d,
            status="published",
            manifest_hash="b" * 64,
            manifest_json={},
            is_monthly_anchor=False,
            storage_tier="local",
            published_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    SnapshotRetention(db_session, snapshots_root=snaps).run(as_of=date.today())
    row = db_session.query(DataSnapshot).filter_by(snapshot_id=sid).one()
    assert row.storage_tier == "deleted"
    assert not (snaps / sid).exists()


@pytest.mark.asyncio
async def test_datalake_router_list(tmp_lake, db_session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.routers.datalake as datalake_mod

    live, snaps = tmp_lake
    pub = SnapshotPublisher(
        db_session,
        live_root=live,
        snapshots_root=snaps,
        quality_gate_fn=lambda: {"passed": True, "dirty_rate_max": 0.02, "sources_checked": []},
    )
    await pub.create_daily_snapshot(date(2026, 7, 13))

    app = FastAPI()
    app.include_router(datalake_mod.router, prefix="/api/v1")

    def _override():
        yield db_session

    app.dependency_overrides[datalake_mod.get_db] = _override
    client = TestClient(app)
    r = client.get("/api/v1/datalake/snapshots")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert any(x["snapshot_id"] == "snap_20260713" for x in body["data"])

    latest = client.get("/api/v1/datalake/snapshots/latest")
    assert latest.status_code == 200
    assert latest.json()["data"]["snapshot_id"] == "snap_20260713"
