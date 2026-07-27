"""补充 services/datalake/snapshot_publisher.py 遗漏分支的覆盖率测试。

覆盖 CI 报告中的缺失行 (47-64, 103-107, 125-244, 263-275, 278-297):
- _sha256_file / _link_or_copy 纯文件辅助函数 (47-64)
- SnapshotPublisher.create_daily_snapshot: 正常发布 / 幂等跳过 / 质量门失败 /
  redis 锁被占用返回 building (125-244)
- _default_quality_gate (109-117)
- default_universe_exporter (278-297)

注: _file_meta (67-88) 与 parquet 拷贝循环 (169-174) 依赖 pyarrow, 本地环境未安装,
故未覆盖; 其余分支均以内存 SQLite + 临时目录隔离测试, 不依赖外部服务。
"""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.datalake_models import Base
from backend.services.datalake import snapshot_publisher as sp
from backend.services.datalake.snapshot_publisher import (
    SnapshotPublisher,
    _link_or_copy,
    _sha256_file,
    default_universe_exporter,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _make_live(tmp_path):
    # 空 ktype 目录: 触发无 parquet 的发布路径 (169-174 因缺 parquet 跳过)
    kdir = tmp_path / "K_DAY"
    kdir.mkdir(parents=True)
    return tmp_path


# ── 纯文件辅助函数 (47-64) ─────────────────────────────────────────────────────
def test_sha256_file(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    h = _sha256_file(f)
    assert len(h) == 64


def test_link_or_copy(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("data")
    dst = tmp_path / "sub" / "dst.txt"
    mode = _link_or_copy(src, dst)
    assert dst.exists()
    assert mode in ("hardlink", "copy2")


# ── create_daily_snapshot 各路径 (125-244) ────────────────────────────────────
@pytest.mark.asyncio
async def test_create_daily_snapshot_published(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "ensure_roots", lambda: None)
    live = _make_live(tmp_path / "live")
    snaps = tmp_path / "snaps"
    pub = SnapshotPublisher(db, live_root=live, snapshots_root=snaps)
    res = await pub.create_daily_snapshot(date(2024, 1, 1))
    assert res.status == "published"
    assert (snaps / "snap_20240101" / "manifest.json").exists()


@pytest.mark.asyncio
async def test_create_daily_snapshot_idempotent(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "ensure_roots", lambda: None)
    live = _make_live(tmp_path / "live")
    snaps = tmp_path / "snaps"
    pub = SnapshotPublisher(db, live_root=live, snapshots_root=snaps)
    first = await pub.create_daily_snapshot(date(2024, 1, 1))
    assert first.status == "published"
    second = await pub.create_daily_snapshot(date(2024, 1, 1))
    assert second.status == "published"
    assert second.message == "idempotent_skip"


@pytest.mark.asyncio
async def test_create_daily_snapshot_quality_gate_fail(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "ensure_roots", lambda: None)

    def _fail_gate():
        return {"passed": False, "dirty_rate_max": 0.05, "dirty_rate_observed": 0.5, "sources_checked": []}

    live = _make_live(tmp_path / "live")
    snaps = tmp_path / "snaps"
    pub = SnapshotPublisher(db, live_root=live, snapshots_root=snaps, quality_gate_fn=_fail_gate)
    res = await pub.create_daily_snapshot(date(2024, 1, 1))
    assert res.status == "failed"
    assert res.message == "quality_gate"


@pytest.mark.asyncio
async def test_create_daily_snapshot_lock_held(db, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "ensure_roots", lambda: None)

    async def _set_none(*a, **k):
        return None  # 锁已被占用

    import backend.core.redis_client as rc_mod

    monkeypatch.setattr(rc_mod.redis_client, "set", _set_none)
    live = _make_live(tmp_path / "live")
    snaps = tmp_path / "snaps"
    pub = SnapshotPublisher(db, live_root=live, snapshots_root=snaps)
    res = await pub.create_daily_snapshot(date(2024, 1, 1))
    assert res.status == "building"
    assert res.message == "lock_held"


def test_default_quality_gate():
    gate = SnapshotPublisher._default_quality_gate()
    assert gate["passed"] is True


def test_default_universe_exporter(tmp_path):
    out = tmp_path / "universe.json"
    res = default_universe_exporter(out)
    assert res["path"] == "sidecars/universe.json"
    assert out.exists()
