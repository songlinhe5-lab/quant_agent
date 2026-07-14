"""
DQ-01: 幸存者偏差处理 — 单元测试
==================================

验证:
  1. TickerLifecycle 存续判断
  2. SurvivorshipBiasTracker 标的池生成
  3. 退市标的正确排除
  4. CSV 导入/导出
  5. 标的池变动 diff
  6. 统计信息
  7. 便捷函数
"""

import csv
import tempfile
from datetime import date
from pathlib import Path

import pytest

from backend.services.survivorship_bias import (
    ListingStatus,
    SurvivorshipBiasTracker,
    TickerLifecycle,
    get_survivorship_tracker,
    get_universe_for_backtest,
)

# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def tracker():
    return SurvivorshipBiasTracker()


@pytest.fixture
def tracker_with_data():
    """预填充数据的 tracker"""
    t = SurvivorshipBiasTracker()
    # 正常存续标的
    t.add_ticker(TickerLifecycle(
        symbol="US.AAPL", name="Apple Inc", market="US",
        list_date=date(1980, 12, 12), status=ListingStatus.LISTED,
    ))
    t.add_ticker(TickerLifecycle(
        symbol="US.MSFT", name="Microsoft", market="US",
        list_date=date(1986, 3, 13), status=ListingStatus.LISTED,
    ))
    # 已退市标的
    t.add_ticker(TickerLifecycle(
        symbol="US.LEH", name="Lehman Brothers", market="US",
        list_date=date(1850, 1, 1), delist_date=date(2008, 9, 15),
        status=ListingStatus.DELISTED, delist_reason="bankruptcy",
    ))
    t.add_ticker(TickerLifecycle(
        symbol="US.ENRN", name="Enron", market="US",
        list_date=date(1985, 1, 1), delist_date=date(2001, 11, 28),
        status=ListingStatus.DELISTED, delist_reason="fraud",
    ))
    # 港股退市标的
    t.add_ticker(TickerLifecycle(
        symbol="HK.00045", name="Test Delisted HK", market="HK",
        list_date=date(2010, 1, 1), delist_date=date(2023, 6, 30),
        status=ListingStatus.DELISTED,
    ))
    return t


# ─────────────────────────────────────────
#  测试: TickerLifecycle 模型
# ─────────────────────────────────────────


class TestTickerLifecycle:
    """DQ-01: 标的生命周期模型"""

    def test_listed_stock_is_alive(self):
        lc = TickerLifecycle(
            symbol="US.AAPL", list_date=date(1980, 12, 12),
            status=ListingStatus.LISTED,
        )
        assert lc.is_alive_on(date(2020, 1, 1)) is True
        assert lc.is_alive_on(date(1980, 12, 12)) is True  # 上市当日

    def test_listed_stock_not_alive_before_listing(self):
        lc = TickerLifecycle(
            symbol="US.AAPL", list_date=date(1980, 12, 12),
            status=ListingStatus.LISTED,
        )
        assert lc.is_alive_on(date(1980, 12, 11)) is False

    def test_delisted_stock_alive_before_delist(self):
        lc = TickerLifecycle(
            symbol="US.LEH", list_date=date(1850, 1, 1),
            delist_date=date(2008, 9, 15), status=ListingStatus.DELISTED,
        )
        assert lc.is_alive_on(date(2008, 9, 14)) is True  # 退市前一日

    def test_delisted_stock_not_alive_on_delist_date(self):
        lc = TickerLifecycle(
            symbol="US.LEH", list_date=date(1850, 1, 1),
            delist_date=date(2008, 9, 15), status=ListingStatus.DELISTED,
        )
        assert lc.is_alive_on(date(2008, 9, 15)) is False  # 退市当日不算

    def test_delisted_stock_not_alive_after_delist(self):
        lc = TickerLifecycle(
            symbol="US.LEH", list_date=date(1850, 1, 1),
            delist_date=date(2008, 9, 15), status=ListingStatus.DELISTED,
        )
        assert lc.is_alive_on(date(2020, 1, 1)) is False

    def test_unknown_status_with_no_dates(self):
        lc = TickerLifecycle(symbol="US.UNKNOWN", status=ListingStatus.UNKNOWN)
        # 无日期信息默认存续（保守策略）
        assert lc.is_alive_on(date(2020, 1, 1)) is True

    def test_was_alive_on_alias(self):
        lc = TickerLifecycle(
            symbol="US.AAPL", list_date=date(1980, 12, 12),
            status=ListingStatus.LISTED,
        )
        assert lc.was_alive_on(date(2020, 1, 1)) == lc.is_alive_on(date(2020, 1, 1))


# ─────────────────────────────────────────
#  测试: 标的池生成
# ─────────────────────────────────────────


class TestUniverseGeneration:
    """DQ-01: 标的池动态生成"""

    def test_universe_excludes_delisted(self, tracker_with_data):
        """核心测试：2020 年的标的池不应包含 2008 退市的 LEH"""
        snapshot = tracker_with_data.get_universe_on(date(2020, 1, 1))
        assert "US.AAPL" in snapshot.tickers
        assert "US.MSFT" in snapshot.tickers
        assert "US.LEH" not in snapshot.tickers  # 2008 退市
        assert "US.ENRN" not in snapshot.tickers  # 2001 退市

    def test_universe_includes_alive_on_early_date(self, tracker_with_data):
        """2000 年 LEH 和 ENRN 都还在"""
        snapshot = tracker_with_data.get_universe_on(date(2000, 6, 1))
        assert "US.LEH" in snapshot.tickers
        assert "US.ENRN" in snapshot.tickers  # 2001-11 才退市
        assert snapshot.total_universe == 5  # 全部存续

    def test_universe_before_enron_delisting(self, tracker_with_data):
        """2001 年 11 月 27 日 ENRN 还在"""
        snapshot = tracker_with_data.get_universe_on(date(2001, 11, 27))
        assert "US.ENRN" in snapshot.tickers

    def test_universe_snapshot_counts(self, tracker_with_data):
        snapshot = tracker_with_data.get_universe_on(date(2020, 1, 1))
        assert snapshot.total_universe == 3  # AAPL, MSFT, HK.00045(2023退市,2020还在)
        assert snapshot.delisted_count == 2  # LEH, ENRN
        assert snapshot.as_of_date == date(2020, 1, 1)

    def test_empty_tracker_universe(self, tracker):
        snapshot = tracker.get_universe_on(date(2020, 1, 1))
        assert snapshot.total_universe == 0
        assert snapshot.tickers == []

    def test_universe_sorted(self, tracker_with_data):
        snapshot = tracker_with_data.get_universe_on(date(2020, 1, 1))
        assert snapshot.tickers == sorted(snapshot.tickers)


# ─────────────────────────────────────────
#  测试: 标的池变动
# ─────────────────────────────────────────


class TestUniverseDiff:
    """DQ-01: 标的池变动"""

    def test_universe_diff_detects_delisting(self, tracker_with_data):
        diff = tracker_with_data.get_universe_diff(
            date(2008, 9, 1), date(2008, 10, 1)
        )
        assert "US.LEH" in diff["removed"]
        assert diff["net_change"] < 0

    def test_universe_diff_no_change(self, tracker_with_data):
        diff = tracker_with_data.get_universe_diff(
            date(2020, 1, 1), date(2020, 2, 1)
        )
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["net_change"] == 0


# ─────────────────────────────────────────
#  测试: 存续状态查询
# ─────────────────────────────────────────


class TestAliveQuery:
    """DQ-01: 存续状态查询"""

    def test_is_alive_for_listed(self, tracker_with_data):
        assert tracker_with_data.is_alive("US.AAPL", date(2020, 1, 1)) is True

    def test_is_alive_for_delisted(self, tracker_with_data):
        assert tracker_with_data.is_alive("US.LEH", date(2020, 1, 1)) is False

    def test_is_alive_unknown_symbol(self, tracker_with_data):
        assert tracker_with_data.is_alive("US.NONEXIST", date(2020, 1, 1)) is False

    def test_get_delisted_tickers(self, tracker_with_data):
        delisted = tracker_with_data.get_delisted_tickers(date(2020, 1, 1))
        assert "US.LEH" in delisted
        assert "US.ENRN" in delisted
        assert "US.AAPL" not in delisted

    def test_get_delisted_tickers_before_delisting(self, tracker_with_data):
        delisted = tracker_with_data.get_delisted_tickers(date(2001, 1, 1))
        assert "US.LEH" not in delisted  # 2008 才退市
        assert "US.ENRN" not in delisted  # 2001-11-28 才退市


# ─────────────────────────────────────────
#  测试: 统计信息
# ─────────────────────────────────────────


class TestStats:
    """DQ-01: 幸存者偏差统计"""

    def test_survivorship_stats(self, tracker_with_data):
        stats = tracker_with_data.get_survivorship_stats(date(2020, 1, 1))
        assert stats["total_records"] == 5
        assert stats["delisted_total"] == 3  # LEH, ENRN, HK.00045
        assert stats["alive_on_date"] == 3  # AAPL, MSFT, HK.00045(alive in 2020)
        assert 0 < stats["survivorship_rate"] < 1.0

    def test_stats_empty_tracker(self, tracker):
        stats = tracker.get_survivorship_stats()
        assert stats["total_records"] == 0
        assert stats["survivorship_rate"] == 0.0


# ─────────────────────────────────────────
#  测试: CSV 导入/导出
# ─────────────────────────────────────────


class TestCSVIO:
    """DQ-01: CSV 导入/导出"""

    def test_load_from_csv(self, tracker):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["symbol", "name", "market", "list_date", "delist_date", "status", "delist_reason"],
            )
            writer.writeheader()
            writer.writerow({
                "symbol": "US.LEH", "name": "Lehman", "market": "US",
                "list_date": "1850-01-01", "delist_date": "2008-09-15",
                "status": "delisted", "delist_reason": "bankruptcy",
            })
            writer.writerow({
                "symbol": "US.AAPL", "name": "Apple", "market": "US",
                "list_date": "1980-12-12", "delist_date": "",
                "status": "listed", "delist_reason": "",
            })
            f.flush()

            count = tracker.load_from_csv(f.name)
            assert count == 2
            assert tracker.total_records == 2

        # 清理
        Path(f.name).unlink()

    def test_load_from_nonexistent_csv(self, tracker):
        count = tracker.load_from_csv("/nonexistent/path.csv")
        assert count == 0

    def test_export_to_csv(self, tracker_with_data):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            count = tracker_with_data.export_to_csv(f.name)
            assert count == tracker_with_data.total_records

        # 验证 CSV 内容
        with open(f.name, "r") as csvf:
            reader = csv.DictReader(csvf)
            rows = list(reader)
            assert len(rows) == 5
            leh_row = next(r for r in rows if r["symbol"] == "US.LEH")
            assert leh_row["status"] == "delisted"
            assert leh_row["delist_date"] == "2008-09-15"

        Path(f.name).unlink()

    def test_csv_roundtrip(self, tracker_with_data):
        """导出再导入，数据应一致"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            tracker_with_data.export_to_csv(f.name)

            new_tracker = SurvivorshipBiasTracker()
            count = new_tracker.load_from_csv(f.name)
            assert count == tracker_with_data.total_records

        Path(f.name).unlink()


# ─────────────────────────────────────────
#  测试: 便捷函数
# ─────────────────────────────────────────


class TestConvenienceFunctions:
    """DQ-01: 便捷函数"""

    def test_get_universe_for_backtest(self, tracker_with_data):
        universe = get_universe_for_backtest(date(2020, 1, 1), tracker_with_data)
        assert isinstance(universe, list)
        assert "US.AAPL" in universe
        assert "US.LEH" not in universe

    def test_get_survivorship_tracker_singleton(self):
        t1 = get_survivorship_tracker()
        t2 = get_survivorship_tracker()
        assert t1 is t2


# ─────────────────────────────────────────
#  测试: 边界场景
# ─────────────────────────────────────────


class TestEdgeCases:
    """DQ-01: 边界场景"""

    def test_add_and_remove(self, tracker):
        lc = TickerLifecycle(symbol="US.TEST", status=ListingStatus.LISTED)
        tracker.add_ticker(lc)
        assert tracker.total_records == 1
        assert tracker.remove_ticker("US.TEST") is True
        assert tracker.total_records == 0

    def test_remove_nonexistent(self, tracker):
        assert tracker.remove_ticker("US.NONEXIST") is False

    def test_update_existing_ticker(self, tracker):
        lc1 = TickerLifecycle(symbol="US.TEST", name="Old", status=ListingStatus.LISTED)
        tracker.add_ticker(lc1)
        assert tracker.get_lifecycle("US.TEST").name == "Old"

        lc2 = TickerLifecycle(symbol="US.TEST", name="New", status=ListingStatus.DELISTED)
        tracker.add_ticker(lc2)
        assert tracker.get_lifecycle("US.TEST").name == "New"
        assert tracker.total_records == 1  # 不重复计数

    def test_batch_add(self, tracker):
        lifecycles = [
            TickerLifecycle(symbol=f"US.STOCK{i}", status=ListingStatus.LISTED)
            for i in range(100)
        ]
        count = tracker.add_batch(lifecycles)
        assert count == 100
        assert tracker.total_records == 100

    def test_mark_loaded(self, tracker):
        assert tracker.is_loaded is False
        tracker.mark_loaded()
        assert tracker.is_loaded is True
