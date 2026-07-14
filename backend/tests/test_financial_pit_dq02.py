"""
DQ-02: 财务数据 Point-in-Time — 单元测试
==========================================

验证:
  1. FinancialDataPoint 模型不变量
  2. PointInTimeStore PIT 查询
  3. 前视偏差拦截
  4. 最新数据获取
  5. 公布时间线
  6. 便捷函数
"""

from datetime import date

import pytest

from backend.services.financial_pit import (
    FinancialDataPoint,
    FinancialDataType,
    FiscalPeriod,
    PITQuery,
    PointInTimeStore,
    get_financial_value,
    get_pit_store,
    is_data_available,
)

# ─────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────


@pytest.fixture
def store():
    return PointInTimeStore()


@pytest.fixture
def store_with_data():
    """预填充 AAPL 财务数据的 store"""
    s = PointInTimeStore()

    # Q3 2024: 报告期 2024-06-29, 公布日 2024-08-01
    s.add(FinancialDataPoint(
        symbol="AAPL",
        data_type=FinancialDataType.EARNINGS,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q3,
        period_end_date=date(2024, 6, 29),
        announce_date=date(2024, 8, 1),
        values={"eps": 1.40, "revenue": 85_777_000_000},
        source="futu",
    ))

    # Q4 2024: 报告期 2024-09-28, 公布日 2024-10-31
    s.add(FinancialDataPoint(
        symbol="AAPL",
        data_type=FinancialDataType.EARNINGS,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q4,
        period_end_date=date(2024, 9, 28),
        announce_date=date(2024, 10, 31),
        values={"eps": 1.64, "revenue": 94_930_000_000},
        source="futu",
    ))

    # Q1 2025: 报告期 2024-12-28, 公布日 2025-01-30
    s.add(FinancialDataPoint(
        symbol="AAPL",
        data_type=FinancialDataType.EARNINGS,
        fiscal_year=2025,
        fiscal_period=FiscalPeriod.Q1,
        period_end_date=date(2024, 12, 28),
        announce_date=date(2025, 1, 30),
        values={"eps": 2.40, "revenue": 124_300_000_000},
        source="futu",
    ))

    # Key Metrics: 2024 Q3
    s.add(FinancialDataPoint(
        symbol="AAPL",
        data_type=FinancialDataType.KEY_METRICS,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q3,
        period_end_date=date(2024, 6, 29),
        announce_date=date(2024, 8, 1),
        values={"pe_ratio": 32.5, "pb_ratio": 45.2, "roe": 1.62},
        source="futu",
    ))

    # 重述数据
    s.add(FinancialDataPoint(
        symbol="AAPL",
        data_type=FinancialDataType.EARNINGS,
        fiscal_year=2024,
        fiscal_period=FiscalPeriod.Q3,
        period_end_date=date(2024, 6, 29),
        announce_date=date(2024, 11, 15),  # 重述公布日晚
        values={"eps": 1.42, "revenue": 85_800_000_000},
        source="futu",
        restated=True,
        restated_from="original_q3_2024",
    ))

    return s


# ─────────────────────────────────────────
#  测试: FinancialDataPoint 模型
# ─────────────────────────────────────────


class TestFinancialDataPoint:
    """DQ-02: 数据点模型"""

    def test_valid_data_point(self):
        dp = FinancialDataPoint(
            symbol="AAPL",
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q3,
            period_end_date=date(2024, 6, 29),
            announce_date=date(2024, 8, 1),
            values={"eps": 1.40},
        )
        assert dp.is_available_on(date(2024, 8, 1)) is True
        assert dp.is_available_on(date(2024, 7, 31)) is False

    def test_invalid_announce_before_period_end(self):
        """announce_date 不能早于 period_end_date"""
        with pytest.raises(ValueError, match="announce_date"):
            FinancialDataPoint(
                symbol="AAPL",
                data_type=FinancialDataType.EARNINGS,
                fiscal_year=2024,
                fiscal_period=FiscalPeriod.Q3,
                period_end_date=date(2024, 6, 29),
                announce_date=date(2024, 6, 1),  # 错误：早于 period_end
                values={"eps": 1.0},
            )

    def test_data_id(self):
        dp = FinancialDataPoint(
            symbol="AAPL",
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q3,
            period_end_date=date(2024, 6, 29),
            announce_date=date(2024, 8, 1),
        )
        assert dp.data_id == "AAPL:earnings:2024Q3"

    def test_same_day_announce_is_available(self):
        """公布日当天算已公布"""
        dp = FinancialDataPoint(
            symbol="TEST",
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q1,
            period_end_date=date(2024, 3, 31),
            announce_date=date(2024, 4, 15),
        )
        assert dp.is_available_on(date(2024, 4, 15)) is True


# ─────────────────────────────────────────
#  测试: PIT 查询
# ─────────────────────────────────────────


class TestPITQuery:
    """DQ-02: Point-in-Time 查询"""

    def test_query_returns_available_only(self, store_with_data):
        """2024-09-01 只能看到 Q3 (公布日 8-1)，看不到 Q4 (公布日 10-31)"""
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2024, 9, 1),
            data_type=FinancialDataType.EARNINGS,
        ))
        assert len(result) == 1
        assert result[0].fiscal_period == FiscalPeriod.Q3

    def test_query_after_all_announced(self, store_with_data):
        """2025-02-01 能看到所有三期"""
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2025, 2, 1),
            data_type=FinancialDataType.EARNINGS,
        ))
        # Q3, Q4, Q1 都公布了 (重述默认不包含)
        assert len(result) == 3

    def test_query_excludes_future_data(self, store_with_data):
        """2024-07-01 看不到任何已公布的 earnings"""
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2024, 7, 1),
            data_type=FinancialDataType.EARNINGS,
        ))
        assert len(result) == 0

    def test_query_filter_by_fiscal_year(self, store_with_data):
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2025, 2, 1),
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
        ))
        assert len(result) == 2  # Q3 + Q4 of FY2024

    def test_query_excludes_restatements_by_default(self, store_with_data):
        """默认不包含重述数据"""
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2025, 2, 1),
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q3,
        ))
        assert len(result) == 1
        assert result[0].restated is False

    def test_query_includes_restatements_when_requested(self, store_with_data):
        """显式请求时包含重述数据"""
        result = store_with_data.query_as_of(PITQuery(
            symbol="AAPL",
            as_of_date=date(2025, 2, 1),
            data_type=FinancialDataType.EARNINGS,
            fiscal_year=2024,
            fiscal_period=FiscalPeriod.Q3,
            include_restatements=True,
        ))
        assert len(result) == 2  # 原始 + 重述

    def test_query_unknown_symbol(self, store_with_data):
        result = store_with_data.query_as_of(PITQuery(
            symbol="NONEXIST",
            as_of_date=date(2025, 1, 1),
        ))
        assert result == []


# ─────────────────────────────────────────
#  测试: 最新数据获取
# ─────────────────────────────────────────


class TestLatestData:
    """DQ-02: 最新数据获取"""

    def test_get_latest_as_of(self, store_with_data):
        latest = store_with_data.get_latest_as_of(
            "AAPL", FinancialDataType.EARNINGS, date(2024, 9, 1)
        )
        assert latest is not None
        assert latest.fiscal_period == FiscalPeriod.Q3
        assert latest.values["eps"] == 1.40

    def test_get_latest_after_newer_announce(self, store_with_data):
        latest = store_with_data.get_latest_as_of(
            "AAPL", FinancialDataType.EARNINGS, date(2024, 11, 1)
        )
        assert latest is not None
        assert latest.fiscal_period == FiscalPeriod.Q4
        assert latest.values["eps"] == 1.64

    def test_get_latest_no_data(self, store_with_data):
        latest = store_with_data.get_latest_as_of(
            "AAPL", FinancialDataType.EARNINGS, date(2020, 1, 1)
        )
        assert latest is None

    def test_get_field_as_of(self, store_with_data):
        pe = store_with_data.get_field_as_of(
            "AAPL", "pe_ratio", date(2024, 9, 1),
            FinancialDataType.KEY_METRICS,
        )
        assert pe == 32.5

    def test_get_field_not_available(self, store_with_data):
        pe = store_with_data.get_field_as_of(
            "AAPL", "pe_ratio", date(2024, 7, 1),
            FinancialDataType.KEY_METRICS,
        )
        assert pe is None  # 还没公布


# ─────────────────────────────────────────
#  测试: 前视偏差检测
# ─────────────────────────────────────────


class TestLookAheadDetection:
    """DQ-02: 前视偏差检测"""

    def test_detect_no_risk_when_all_available(self, store_with_data):
        result = store_with_data.detect_look_ahead_risk(
            "AAPL", date(2025, 2, 1), FinancialDataType.EARNINGS
        )
        assert result["risk_level"] == "safe"
        assert result["not_yet_available_count"] == 0

    def test_detect_risk_when_data_pending(self, store_with_data):
        result = store_with_data.detect_look_ahead_risk(
            "AAPL", date(2024, 9, 1), FinancialDataType.EARNINGS
        )
        assert result["risk_level"] == "warning"
        assert result["not_yet_available_count"] > 0

    def test_days_until_next_announce(self, store_with_data):
        result = store_with_data.detect_look_ahead_risk(
            "AAPL", date(2024, 9, 1), FinancialDataType.EARNINGS
        )
        # Q4 公布日 10-31, 距离 9-01 有 60 天
        assert result["days_until_next_announce"] is not None
        assert result["days_until_next_announce"] > 0

    def test_detect_unknown_symbol(self, store_with_data):
        result = store_with_data.detect_look_ahead_risk("NONEXIST", date(2024, 9, 1))
        assert result["available_count"] == 0


# ─────────────────────────────────────────
#  测试: 公布时间线
# ─────────────────────────────────────────


class TestTimeline:
    """DQ-02: 公布时间线"""

    def test_announce_timeline(self, store_with_data):
        timeline = store_with_data.get_announce_timeline("AAPL")
        assert len(timeline) >= 4
        # 验证 lag_days 计算
        q3 = next(t for t in timeline if t["fiscal_period"] == "2024Q3" and not t["restated"])
        assert q3["lag_days"] == (date(2024, 8, 1) - date(2024, 6, 29)).days

    def test_timeline_empty(self, store):
        timeline = store.get_announce_timeline("NONEXIST")
        assert timeline == []


# ─────────────────────────────────────────
#  测试: 统计信息
# ─────────────────────────────────────────


class TestStats:
    """DQ-02: 统计信息"""

    def test_stats(self, store_with_data):
        # 触发一些查询
        store_with_data.query_as_of(PITQuery(symbol="AAPL", as_of_date=date(2024, 9, 1)))
        stats = store_with_data.get_stats()
        assert stats["total_records"] >= 5
        assert stats["symbols_count"] == 1
        assert stats["query_count"] >= 1


# ─────────────────────────────────────────
#  测试: 便捷函数
# ─────────────────────────────────────────


class TestConvenienceFunctions:
    """DQ-02: 便捷函数"""

    def test_get_financial_value(self, store_with_data):
        eps = get_financial_value(
            "AAPL", "eps", date(2024, 9, 1),
            FinancialDataType.EARNINGS, store_with_data,
        )
        assert eps == 1.40

    def test_get_financial_value_not_available(self, store_with_data):
        eps = get_financial_value(
            "AAPL", "eps", date(2024, 7, 1),
            FinancialDataType.EARNINGS, store_with_data,
        )
        assert eps is None

    def test_is_data_available_true(self, store_with_data):
        assert is_data_available(
            "AAPL", FinancialDataType.EARNINGS, 2024, FiscalPeriod.Q3,
            date(2024, 9, 1), store_with_data,
        ) is True

    def test_is_data_available_false(self, store_with_data):
        assert is_data_available(
            "AAPL", FinancialDataType.EARNINGS, 2024, FiscalPeriod.Q4,
            date(2024, 9, 1), store_with_data,
        ) is False  # Q4 还没公布

    def test_get_pit_store_singleton(self):
        s1 = get_pit_store()
        s2 = get_pit_store()
        assert s1 is s2


# ─────────────────────────────────────────
#  测试: 边界场景
# ─────────────────────────────────────────


class TestEdgeCases:
    """DQ-02: 边界场景"""

    def test_batch_add(self, store):
        points = [
            FinancialDataPoint(
                symbol=f"STOCK{i}",
                data_type=FinancialDataType.EARNINGS,
                fiscal_year=2024,
                fiscal_period=FiscalPeriod.Q1,
                period_end_date=date(2024, 3, 31),
                announce_date=date(2024, 4, 30),
                values={"eps": 1.0},
            )
            for i in range(50)
        ]
        count = store.add_batch(points)
        assert count == 50
        assert store.total_records == 50

    def test_multiple_symbols(self, store):
        for sym in ["AAPL", "MSFT", "GOOG"]:
            store.add(FinancialDataPoint(
                symbol=sym,
                data_type=FinancialDataType.EARNINGS,
                fiscal_year=2024,
                fiscal_period=FiscalPeriod.Q1,
                period_end_date=date(2024, 3, 31),
                announce_date=date(2024, 4, 30),
                values={"eps": 1.0},
            ))
        assert store.total_records == 3
        assert set(store.symbols) == {"AAPL", "MSFT", "GOOG"}

    def test_query_increments_counter(self, store_with_data):
        initial = store_with_data._query_count
        store_with_data.query_as_of(PITQuery(symbol="AAPL", as_of_date=date(2024, 9, 1)))
        assert store_with_data._query_count == initial + 1
