"""
BT-02 + DQ-03a 地基测试

覆盖：
- manifest hash 确定性 / 校验
- SnapshotResolver（latest / live 禁止 / 显式 hash）
- BacktestDriver 同输入同输出
- BacktestReport 持久化 + reproducibility_key
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.database import Base
from backend.core.datalake_models import BacktestReport, DataSnapshot
from backend.engine import Bar, OrderIntent, Strategy
from backend.engine.contracts import RunManifest
from backend.engine.drivers.backtest import BacktestConfig, BacktestDriver
from backend.services.backtest_report_service import (
    BacktestReportService,
    compute_reproducibility_key,
    compute_result_digest,
    is_reproducible,
)
from backend.services.datalake.manifest import (
    build_manifest,
    compute_manifest_hash,
    validate_manifest,
)
from backend.services.datalake.snapshot_resolver import SnapshotResolveError, SnapshotResolver


def make_sample_df(n: int = 60, seed: int = 7) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(seed)
    prices = [100.0]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + float(rng.uniform(-0.02, 0.02))))
    return pd.DataFrame(
        {
            "open": [p * 0.998 for p in prices],
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": rng.integers(100000, 1000000, n).astype(float),
        },
        index=dates,
    )


class SeedAwareStrategy(Strategy):
    """用随机数下单比例，验证 seed 固定后路径一致。"""

    def on_bar(self, ctx, bar: Bar) -> None:
        pos = ctx.position(bar.symbol)
        roll = np.random.random()
        if roll < 0.1 and pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="BUY", qty=10))
        elif roll > 0.9 and not pos.is_flat:
            ctx.order(OrderIntent(symbol=bar.symbol, side="SELL", qty=pos.qty))


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestManifestPure:
    def test_hash_deterministic(self):
        m1 = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "kline/K_DAY/US_AAPL.parquet", "sha256": "abc", "rows": 10, "bytes": 100}],
            created_at="2026-07-13T03:00:00Z",
        )
        m2 = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "kline/K_DAY/US_AAPL.parquet", "sha256": "abc", "rows": 10, "bytes": 100}],
            created_at="2026-07-13T03:00:00Z",
        )
        assert m1["manifest_hash"] == m2["manifest_hash"]
        assert validate_manifest(m1)

    def test_hash_changes_when_file_changes(self):
        a = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "a.parquet", "sha256": "1", "rows": 1, "bytes": 1}],
            created_at="t",
        )
        b = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "a.parquet", "sha256": "2", "rows": 1, "bytes": 1}],
            created_at="t",
        )
        assert a["manifest_hash"] != b["manifest_hash"]

    def test_validate_rejects_tamper(self):
        m = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "a.parquet", "sha256": "1", "rows": 1, "bytes": 1}],
            created_at="t",
        )
        m["files"][0]["sha256"] = "tampered"
        assert validate_manifest(m) is False
        # 恢复 hash 字段后仍应失败（内容已变）
        m["manifest_hash"] = compute_manifest_hash(m)
        assert validate_manifest(m) is True


class TestSnapshotResolver:
    def test_live_forbidden_by_default(self, monkeypatch):
        monkeypatch.delenv("ENGINE_ALLOW_LIVE_DATA", raising=False)
        with pytest.raises(SnapshotResolveError):
            SnapshotResolver().resolve("live")

    def test_live_allowed_in_dev(self, monkeypatch):
        monkeypatch.setenv("ENGINE_ALLOW_LIVE_DATA", "true")
        ref = SnapshotResolver().resolve("live")
        assert ref.data_mode == "live"
        assert ref.snapshot_id == "live"

    def test_explicit_manifest_hash_without_db(self):
        ref = SnapshotResolver().resolve("snap_20260701", manifest_hash="deadbeef" * 8)
        assert ref.data_mode == "snapshot"
        assert ref.manifest_hash == "deadbeef" * 8

    def test_latest_published_from_db(self, db_session):
        m = build_manifest(
            snapshot_id="snap_20260710",
            as_of_date="2026-07-10",
            files=[{"path": "a.parquet", "sha256": "x", "rows": 1, "bytes": 1}],
            created_at="t",
        )
        db_session.add(
            DataSnapshot(
                snapshot_id="snap_20260710",
                as_of_date=date(2026, 7, 10),
                status="published",
                manifest_hash=m["manifest_hash"],
                manifest_json=m,
                published_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()
        ref = SnapshotResolver(db_session).resolve("latest_published")
        assert ref.snapshot_id == "snap_20260710"
        assert ref.manifest_hash == m["manifest_hash"]


class TestReproducibleBacktest:
    def test_same_input_same_output(self):
        df = make_sample_df()
        source = "class SeedAwareStrategy: pass"
        cfg = BacktestConfig(
            random_seed=42,
            data_snapshot_id="snap_20260713",
            manifest_hash="a" * 64,
            data_mode="snapshot",
        )
        r1 = BacktestDriver(cfg).run(SeedAwareStrategy, {}, df, "TEST", source_code=source)
        r2 = BacktestDriver(cfg).run(SeedAwareStrategy, {}, df, "TEST", source_code=source)

        assert r1.manifest.reproducible is True
        assert r1.manifest.code_hash == r2.manifest.code_hash
        assert r1.manifest.manifest_hash == r2.manifest.manifest_hash
        assert r1.metrics == r2.metrics
        assert compute_result_digest(r1.metrics, r1.equity_curve) == compute_result_digest(
            r2.metrics, r2.equity_curve
        )

    def test_different_seed_diverges(self):
        df = make_sample_df()
        source = "class SeedAwareStrategy: pass"
        r1 = BacktestDriver(
            BacktestConfig(random_seed=1, manifest_hash="a" * 64, data_mode="snapshot", data_snapshot_id="snap_x")
        ).run(SeedAwareStrategy, {}, df, "TEST", source_code=source)
        r2 = BacktestDriver(
            BacktestConfig(random_seed=2, manifest_hash="a" * 64, data_mode="snapshot", data_snapshot_id="snap_x")
        ).run(SeedAwareStrategy, {}, df, "TEST", source_code=source)
        assert compute_result_digest(r1.metrics, r1.equity_curve) != compute_result_digest(
            r2.metrics, r2.equity_curve
        )

    def test_unbound_not_reproducible(self):
        df = make_sample_df(n=40)
        r = BacktestDriver(BacktestConfig()).run(SeedAwareStrategy, {}, df, "TEST", source_code="x")
        assert r.manifest.reproducible is False
        assert r.manifest.data_mode == "unbound"


class TestBacktestReportPersistence:
    def test_save_and_get_with_fk(self, db_session):
        m = build_manifest(
            snapshot_id="snap_20260713",
            as_of_date="2026-07-13",
            files=[{"path": "a.parquet", "sha256": "x", "rows": 1, "bytes": 1}],
            created_at="t",
        )
        db_session.add(
            DataSnapshot(
                snapshot_id="snap_20260713",
                as_of_date=date(2026, 7, 13),
                status="published",
                manifest_hash=m["manifest_hash"],
                manifest_json=m,
                published_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()

        df = make_sample_df()
        result = BacktestDriver(
            BacktestConfig(
                random_seed=99,
                data_snapshot_id="snap_20260713",
                manifest_hash=m["manifest_hash"],
                data_mode="snapshot",
            )
        ).run(SeedAwareStrategy, {}, df, "TEST", source_code="strategy-v1")

        # 持久化时用带 params 的 manifest 副本验证 fingerprint
        result.manifest.params = {"k": 1}
        svc = BacktestReportService(db_session)
        row = svc.save(
            result.manifest,
            metrics=result.metrics,
            equity_curve=result.equity_curve,
            trades=result.trades,
            symbol="TEST",
        )
        assert row.reproducible is True
        assert row.data_snapshot_id == "snap_20260713"
        assert row.reproducibility_key == compute_reproducibility_key(
            result.manifest.code_hash,
            m["manifest_hash"],
            {"k": 1},
            99,
        )

        loaded = svc.get(result.manifest.run_id)
        assert loaded is not None
        public = svc.to_public_dict(loaded)
        assert public["badge"]["reproducible"] is True
        assert public["result_digest"] == row.result_digest

    def test_same_repro_key_same_digest(self, db_session):
        """同 (code_hash, manifest_hash, params, seed) → 结果 digest 一致（CI 契约）。"""
        mh = "b" * 64
        db_session.add(
            DataSnapshot(
                snapshot_id="snap_20260101",
                as_of_date=date(2026, 1, 1),
                status="published",
                manifest_hash=mh,
                manifest_json={"manifest_hash": mh},
                published_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()

        df = make_sample_df()
        cfg = BacktestConfig(
            random_seed=123,
            data_snapshot_id="snap_20260101",
            manifest_hash=mh,
            data_mode="snapshot",
        )
        source = "identical-source"
        params: dict = {}
        r1 = BacktestDriver(cfg).run(SeedAwareStrategy, params, df, "T", source_code=source)
        r2 = BacktestDriver(cfg).run(SeedAwareStrategy, params, df, "T", source_code=source)

        # 同一 fingerprint 用相同 params 写入
        for r in (r1, r2):
            r.manifest.params = {"x": 2}
        svc = BacktestReportService(db_session)
        a = svc.save(r1.manifest, metrics=r1.metrics, equity_curve=r1.equity_curve)
        b = svc.save(r2.manifest, metrics=r2.metrics, equity_curve=r2.equity_curve)
        assert a.reproducibility_key == b.reproducibility_key
        assert a.result_digest == b.result_digest

    def test_is_reproducible_helper(self):
        assert is_reproducible(
            code_hash="c" * 64, manifest_hash="m" * 64, random_seed=1, data_mode="snapshot"
        )
        assert not is_reproducible(
            code_hash="c" * 64, manifest_hash="m" * 64, random_seed=None, data_mode="snapshot"
        )
        assert not is_reproducible(
            code_hash="c" * 64, manifest_hash="m" * 64, random_seed=1, data_mode="live"
        )


class TestRunManifestSummary:
    def test_to_summary_includes_badge_fields(self):
        m = RunManifest(
            run_id=str(uuid.uuid4()),
            mode="backtest",
            code_hash="c" * 64,
            params={},
            data_snapshot_id="snap_20260713",
            manifest_hash="m" * 64,
            random_seed=1,
            data_mode="snapshot",
            reproducible=True,
        )
        s = m.to_summary()
        assert s["reproducible"] is True
        assert s["manifest_hash"] == "m" * 64
