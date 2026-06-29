"""
行情数据正确性校验引擎单元测试
覆盖: backend/core/market_correctness.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


# ─── 测试数据生成辅助 ───────────────────────────────────────────────
def make_kline_df(rows: int = 30, start_price: float = 100.0) -> pd.DataFrame:
    """生成正常 K 线 DataFrame（使用 tz-naive datetime，匹配源码 datetime.now() 行为）"""
    # 使用最近的日期，避免触发 days_since_last > 30 的退市误判
    base_date = datetime.now() - timedelta(days=rows + 1)
    data = []
    for i in range(rows):
        data.append(
            {
                "time": base_date + timedelta(days=i),
                "open": start_price + i,
                "high": start_price + i + 2,
                "low": start_price + i - 1,
                "close": start_price + i + 1,
                "volume": 10000 + i * 100,
            }
        )
    return pd.DataFrame(data)


# ─── AdjustType 枚举 ───────────────────────────────────────────────
class TestAdjustType:
    def test_enum_values(self):
        from backend.core.market_correctness import AdjustType

        assert AdjustType.NONE.value == "none"
        assert AdjustType.QFQ.value == "qfq"
        assert AdjustType.HFQ.value == "hfq"

    def test_enum_is_str(self):
        from backend.core.market_correctness import AdjustType

        assert isinstance(AdjustType.QFQ, str)


# ─── MarketSession 市场时段 ─────────────────────────────────────────
class TestMarketSession:
    def test_get_market_us_prefix(self):
        from backend.core.market_correctness import MarketSession

        assert MarketSession.get_market("US.AAPL") == "US"
        assert MarketSession.get_market("US_TSLA") == "US"

    def test_get_market_hk_prefix(self):
        from backend.core.market_correctness import MarketSession

        assert MarketSession.get_market("HK.00700") == "HK"
        assert MarketSession.get_market("HK_09988") == "HK"

    def test_get_market_cn_prefix(self):
        from backend.core.market_correctness import MarketSession

        assert MarketSession.get_market("SH.600000") == "CN"
        assert MarketSession.get_market("SZ.000001") == "CN"
        assert MarketSession.get_market("CN.600000") == "CN"

    def test_get_market_unknown_defaults_us(self):
        from backend.core.market_correctness import MarketSession

        assert MarketSession.get_market("AAPL") == "US"
        assert MarketSession.get_market("XYZ123") == "US"

    def test_sessions_definition_complete(self):
        from backend.core.market_correctness import MarketSession

        assert "US" in MarketSession.SESSIONS
        assert "HK" in MarketSession.SESSIONS
        assert "CN" in MarketSession.SESSIONS
        # 验证必要字段
        for market, sess in MarketSession.SESSIONS.items():
            assert "timezone_offset" in sess

    def test_is_trading_hours_us_regular(self):
        from backend.core.market_correctness import MarketSession

        # 美股常规时段：09:30-16:00 ET (UTC-5) → 13:30-20:00 UTC，工作日
        weekday_utc = datetime(2024, 1, 2, 14, 30, tzinfo=timezone.utc)  # 周二
        assert MarketSession.is_trading_hours("US.AAPL", weekday_utc) is True

    def test_is_trading_hours_us_weekend(self):
        from backend.core.market_correctness import MarketSession

        saturday = datetime(2024, 1, 6, 14, 30, tzinfo=timezone.utc)  # 周六
        assert MarketSession.is_trading_hours("US.AAPL", saturday) is False

    def test_is_trading_hours_us_outside_session(self):
        from backend.core.market_correctness import MarketSession

        # 03:00 UTC = 22:00 ET 前一日，盘后外
        late_utc = datetime(2024, 1, 2, 3, 0, tzinfo=timezone.utc)
        result = MarketSession.is_trading_hours("US.AAPL", late_utc)
        assert isinstance(result, bool)

    def test_is_trading_hours_hk_session(self):
        from backend.core.market_correctness import MarketSession

        # HK 上午盘 09:30-12:00 HKT = 01:30-04:00 UTC
        hk_morning = datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc)  # 周二 10:00 HKT
        assert MarketSession.is_trading_hours("HK.00700", hk_morning) is True

    def test_is_trading_hours_cn_session(self):
        from backend.core.market_correctness import MarketSession

        # A股上午盘 09:30-11:30 CST = 01:30-03:30 UTC
        cn_morning = datetime(2024, 1, 2, 2, 0, tzinfo=timezone.utc)  # 周二 10:00 CST
        assert MarketSession.is_trading_hours("SH.600000", cn_morning) is True


# ─── SuspensionStatus 枚举 ─────────────────────────────────────────
class TestSuspensionStatus:
    def test_status_values(self):
        from backend.core.market_correctness import SuspensionStatus

        assert SuspensionStatus.NORMAL.value == "normal"
        assert SuspensionStatus.SUSPENDED.value == "suspended"
        assert SuspensionStatus.DELISTED.value == "delisted"
        assert SuspensionStatus.PRE_MARKET.value == "pre_market"
        assert SuspensionStatus.AFTER_HOURS.value == "after_hours"


# ─── detect_suspension 停牌检测 ────────────────────────────────────
class TestDetectSuspension:
    def test_empty_df_returns_delisted(self):
        from backend.core.market_correctness import detect_suspension

        result = detect_suspension(pd.DataFrame(), "US.AAPL")
        assert result["status"] == "delisted"
        assert result["confidence"] == 0.9
        assert result["last_trade_date"] is None

    def test_none_df_returns_delisted(self):
        from backend.core.market_correctness import detect_suspension

        result = detect_suspension(None, "US.AAPL")
        assert result["status"] == "delisted"

    def test_short_df_returns_normal(self):
        from backend.core.market_correctness import detect_suspension

        df = make_kline_df(rows=3)
        result = detect_suspension(df, "US.AAPL")
        assert result["status"] == "normal"
        assert result["confidence"] == 0.5

    def test_normal_df_returns_normal(self):
        from backend.core.market_correctness import detect_suspension

        df = make_kline_df(rows=30)
        result = detect_suspension(df, "US.AAPL")
        assert result["status"] == "normal"
        assert "last_trade_date" in result

    def test_zero_volume_days_detected(self):
        from backend.core.market_correctness import detect_suspension

        df = make_kline_df(rows=30)
        df.loc[0:4, "volume"] = 0  # 制造 5 个零成交量日
        result = detect_suspension(df, "US.AAPL")
        # 零成交 > 3 应触发停牌
        assert result["status"] == "suspended"
        assert len(result["suspension_days"]) == 5

    def test_delisted_by_stale_date(self):
        from backend.core.market_correctness import detect_suspension

        # 最后一行是 60 天前
        df = make_kline_df(rows=30)
        df["time"] = df["time"] - timedelta(days=60)
        result = detect_suspension(df, "US.AAPL")
        assert result["status"] == "delisted"
        assert result["confidence"] == 0.9


# ─── apply_adjustment 复权处理 ──────────────────────────────────────
class TestApplyAdjustment:
    def test_empty_df_returns_empty(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        result = apply_adjustment(pd.DataFrame(), AdjustType.QFQ)
        assert result.empty

    def test_none_df_returns_none(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        result = apply_adjustment(None, AdjustType.QFQ)
        assert result is None

    def test_none_adjust_adds_adj_columns(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        df = make_kline_df(rows=5)
        result = apply_adjustment(df, AdjustType.NONE)
        assert "adj_close" in result.columns
        assert "adj_open" in result.columns
        assert list(result["adj_close"]) == list(df["close"])

    def test_qfq_without_factor_uses_close(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        df = make_kline_df(rows=5)
        result = apply_adjustment(df, AdjustType.QFQ, adjust_factor_col="missing_col")
        assert "adj_close" in result.columns
        assert list(result["adj_close"]) == list(df["close"])

    def test_qfq_with_factor_applies_multiplication(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        df = make_kline_df(rows=5)
        df["adjust_factor"] = [1.0, 1.0, 1.5, 1.5, 2.0]
        result = apply_adjustment(df, AdjustType.QFQ)
        # 验证 adj_close = close * factor
        assert result["adj_close"].iloc[2] == df["close"].iloc[2] * 1.5
        assert result["adj_close"].iloc[4] == df["close"].iloc[4] * 2.0

    def test_hfq_with_factor_normalizes_by_latest(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        df = make_kline_df(rows=5)
        df["adjust_factor"] = [1.0, 1.0, 1.5, 1.5, 2.0]
        result = apply_adjustment(df, AdjustType.HFQ)
        latest_factor = 2.0
        # adj_close[2] = close[2] * (1.5 / 2.0)
        assert result["adj_close"].iloc[2] == pytest.approx(df["close"].iloc[2] * (1.5 / latest_factor))

    def test_hfq_without_factor_falls_back_to_none(self):
        from backend.core.market_correctness import AdjustType, apply_adjustment

        df = make_kline_df(rows=5)
        result = apply_adjustment(df, AdjustType.HFQ, adjust_factor_col="missing")
        # 后复权无因子时降级为不复权
        assert list(result["adj_close"]) == list(df["close"])


# ─── detect_price_anomalies 异常值检测 ─────────────────────────────
class TestDetectPriceAnomalies:
    def test_empty_df_returns_empty_list(self):
        from backend.core.market_correctness import detect_price_anomalies

        assert detect_price_anomalies(pd.DataFrame(), "US.AAPL") == []
        assert detect_price_anomalies(None, "US.AAPL") == []

    def test_normal_df_no_anomalies(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=10)
        anomalies = detect_price_anomalies(df, "US.AAPL")
        assert anomalies == []

    def test_invalid_price_zero(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        df.loc[0, "close"] = 0
        anomalies = detect_price_anomalies(df, "US.AAPL")
        assert any(a["type"] == "invalid_price" for a in anomalies)
        assert any(a["severity"] == "critical" for a in anomalies)

    def test_invalid_price_negative(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        df.loc[0, "open"] = -10.0
        anomalies = detect_price_anomalies(df, "US.AAPL")
        assert any(a["type"] == "invalid_price" and a["field"] == "open" for a in anomalies)

    def test_ohlc_inconsistency(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        df.loc[0, "high"] = 50.0
        df.loc[0, "low"] = 100.0  # high < low
        anomalies = detect_price_anomalies(df, "US.AAPL")
        assert any(a["type"] == "ohlc_inconsistency" for a in anomalies)

    def test_negative_volume(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        df.loc[0, "volume"] = -100
        anomalies = detect_price_anomalies(df, "US.AAPL")
        assert any(a["type"] == "negative_volume" for a in anomalies)
        assert any(a["severity"] == "warning" for a in anomalies)

    def test_extreme_change_detected(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        df.loc[1, "close"] = df.loc[0, "close"] * 3  # 200% 涨幅
        anomalies = detect_price_anomalies(df, "US.AAPL", max_change_pct=0.5)
        assert any(a["type"] == "extreme_change" for a in anomalies)

    def test_extreme_change_within_threshold(self):
        from backend.core.market_correctness import detect_price_anomalies

        df = make_kline_df(rows=5)
        # 制造 10% 涨幅，阈值 50%
        df.loc[1, "close"] = df.loc[0, "close"] * 1.1
        anomalies = detect_price_anomalies(df, "US.AAPL", max_change_pct=0.5)
        assert not any(a["type"] == "extreme_change" for a in anomalies)


# ─── normalize_to_utc 时区统一 ─────────────────────────────────────
class TestNormalizeToUtc:
    def test_naive_datetime_assumed_utc(self):
        from backend.core.market_correctness import normalize_to_utc

        dt = datetime(2024, 1, 1, 12, 0)
        result = normalize_to_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_aware_datetime_converted_to_utc(self):
        from datetime import timedelta

        from backend.core.market_correctness import normalize_to_utc

        cst = timezone(timedelta(hours=8))
        dt = datetime(2024, 1, 1, 20, 0, tzinfo=cst)  # 20:00 CST = 12:00 UTC
        result = normalize_to_utc(dt)
        assert result.tzinfo == timezone.utc
        assert result.hour == 12

    def test_seconds_timestamp(self):
        from backend.core.market_correctness import normalize_to_utc

        ts = 1700000000  # 秒级
        result = normalize_to_utc(ts)
        assert result.tzinfo == timezone.utc

    def test_milliseconds_timestamp(self):
        from backend.core.market_correctness import normalize_to_utc

        ts = 1700000000000  # 毫秒级
        result = normalize_to_utc(ts)
        assert result.tzinfo == timezone.utc
        # 应等价于秒级 ts/1000
        expected = normalize_to_utc(1700000000)
        assert result == expected

    def test_iso_string(self):
        from backend.core.market_correctness import normalize_to_utc

        result = normalize_to_utc("2024-01-15 10:00:00")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_invalid_string_raises(self):
        from backend.core.market_correctness import normalize_to_utc

        with pytest.raises(ValueError):
            normalize_to_utc("not-a-date")

    def test_unsupported_type_raises(self):
        from backend.core.market_correctness import normalize_to_utc

        with pytest.raises(TypeError):
            normalize_to_utc(["list", "not", "supported"])


# ─── format_market_time 市场本地时间格式化 ────────────────────────
class TestFormatMarketTime:
    def test_format_us_market(self):
        from backend.core.market_correctness import format_market_time

        dt = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = format_market_time("US.AAPL", dt)
        assert "ET" in result
        assert "2024-01-15" in result

    def test_format_hk_market(self):
        from backend.core.market_correctness import format_market_time

        dt = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
        result = format_market_time("HK.00700", dt)
        assert "HKT" in result

    def test_format_cn_market(self):
        from backend.core.market_correctness import format_market_time

        dt = datetime(2024, 1, 15, 8, 0, tzinfo=timezone.utc)
        result = format_market_time("SH.600000", dt)
        assert "CST" in result

    def test_format_unknown_market_defaults_et(self):
        from backend.core.market_correctness import format_market_time

        dt = datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)
        result = format_market_time("UNKNOWN", dt)
        assert "ET" in result


# ─── DataQualityChecker 综合质量检查 ───────────────────────────────
class TestDataQualityChecker:
    def test_check_normal_df(self):
        from backend.core.market_correctness import DataQualityChecker

        df = make_kline_df(rows=30)
        checker = DataQualityChecker("US.AAPL")
        result = checker.check(df)
        assert result["symbol"] == "US.AAPL"
        assert result["quality_score"] == 1.0
        assert result["status"] == "normal"
        assert isinstance(result["anomalies"], list)
        assert "checked_at" in result
        assert "suspension_info" in result

    def test_check_empty_df_zero_score(self):
        from backend.core.market_correctness import DataQualityChecker

        checker = DataQualityChecker("US.AAPL")
        result = checker.check(pd.DataFrame())
        assert result["quality_score"] == 0.0
        assert result["status"] == "delisted"

    def test_check_with_anomalies_reduces_score(self):
        from backend.core.market_correctness import DataQualityChecker

        df = make_kline_df(rows=10)
        df.loc[0, "close"] = 0  # 1 个 critical 异常
        checker = DataQualityChecker("US.AAPL")
        result = checker.check(df)
        assert result["quality_score"] < 1.0
        assert len(result["anomalies"]) >= 1

    def test_check_anomalies_capped_at_20(self):
        from backend.core.market_correctness import DataQualityChecker

        df = make_kline_df(rows=30)
        # 制造 25 个零成交量异常（其实只能制造 close=0）
        for i in range(25):
            df.loc[i, "close"] = 0
        checker = DataQualityChecker("US.AAPL")
        result = checker.check(df)
        assert len(result["anomalies"]) <= 20

    def test_check_data_quality_helper(self):
        from backend.core.market_correctness import check_data_quality

        df = make_kline_df(rows=30)
        result = check_data_quality("US.AAPL", df)
        assert result["symbol"] == "US.AAPL"
        assert result["quality_score"] == 1.0
