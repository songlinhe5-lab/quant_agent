"""yfinance technical 指标计算单元测试 — 纯 pandas 逻辑, 无外部依赖。"""

import numpy as np
import pandas as pd

from data_subservice._internal.yfinance import technical


def _make_df(n=250, start=100.0, step=0.5):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [start + i * step for i in range(n)]
    return pd.DataFrame(
        {"Date": dates, "Close": close, "Open": close, "High": close, "Low": close, "Volume": [1000] * n}
    )


def _rising(n=250):
    # 整体上行 + 小幅波动, 使 RSI 进入 overbought 且非 NaN
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100 + i + 2 * np.sin(i / 5) for i in range(n)]
    return pd.DataFrame(
        {"Date": dates, "Close": close, "Open": close, "High": close, "Low": close, "Volume": [1000] * n}
    )


def _falling(n=250):
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [200 - i - 2 * np.sin(i / 5) for i in range(n)]
    return pd.DataFrame(
        {"Date": dates, "Close": close, "Open": close, "High": close, "Low": close, "Volume": [1000] * n}
    )


class TestResolvePeriodRange:
    def test_known_period(self):
        assert technical.resolve_period_range("1mo") == ("1mo", "1h")

    def test_all_periods(self):
        for p in ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]:
            assert len(technical.resolve_period_range(p)) == 2

    def test_invalid_period_raises(self):
        import pytest

        with pytest.raises(ValueError):
            technical.resolve_period_range("99y")


class TestCalculateTechnicalIndicators:
    def test_empty_df_returns_empty(self):
        assert technical.calculate_technical_indicators(pd.DataFrame()) == {}
        assert technical.calculate_technical_indicators(None) == {}

    def test_default_all_indicators(self):
        df = _make_df()
        res = technical.calculate_technical_indicators(df)
        assert "SMA_20" in res and "SMA_50" in res and "SMA_200" in res
        assert "EMA_12" in res and "EMA_26" in res
        assert "RSI_14" in res
        assert "MACD" in res
        assert set(res["MACD"].keys()) == {"macd", "signal", "hist"}

    def test_only_sma(self):
        df = _make_df()
        res = technical.calculate_technical_indicators(df, indicators=["SMA"])
        assert set(res.keys()) == {"SMA_20", "SMA_50", "SMA_200"}

    def test_short_series_skips_long_windows(self):
        # 仅 30 行, 应只算 SMA_20 (>=20), 跳过 50/200
        df = _make_df(n=30)
        res = technical.calculate_technical_indicators(df, indicators=["SMA"])
        assert "SMA_20" in res
        assert "SMA_50" not in res
        assert "SMA_200" not in res

    def test_rsi_bounds(self):
        df = _make_df()
        res = technical.calculate_technical_indicators(df, indicators=["RSI"])
        vals = [v for v in res["RSI_14"] if v is not None]
        assert all(0 <= v <= 100 for v in vals)

    def test_macd_signal_present(self):
        df = _make_df()
        res = technical.calculate_technical_indicators(df, indicators=["MACD"])
        assert len(res["MACD"]["macd"]) == 250
        assert len(res["MACD"]["signal"]) == 250

    def test_date_index_used(self):
        # Date 列被设为索引; 重复验证无异常
        df = _make_df()
        res = technical.calculate_technical_indicators(df)
        assert "SMA_20" in res

    def test_ema_values_finite(self):
        df = _make_df()
        res = technical.calculate_technical_indicators(df, indicators=["EMA"])
        assert all(v is not None and np.isfinite(v) for v in res["EMA_12"])


class TestDetectSignals:
    def test_empty(self):
        assert technical.detect_signals(pd.DataFrame()) == {"macd": "neutral", "rsi": "neutral", "trend": "neutral"}

    def test_bullish_trend(self):
        df = _rising(n=250)
        sig = technical.detect_signals(df)
        assert sig["trend"] == "bullish"

    def test_bearish_trend(self):
        df = _falling(n=250)
        sig = technical.detect_signals(df)
        assert sig["trend"] == "bearish"

    def test_neutral_trend_short_series(self):
        df = _make_df(n=50)
        sig = technical.detect_signals(df)
        # 不足 200 行, trend 保持 neutral
        assert sig["trend"] == "neutral"

    def test_overbought_rsi(self):
        # 连续上涨为主、偶极小回落 → RSI>70 且非 NaN
        n = 250
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        price = 100.0
        close = []
        for i in range(n):
            price += 1.0 if i % 10 != 0 else -0.5
            close.append(price)
        df = pd.DataFrame({"Date": dates, "Close": close})
        sig = technical.detect_signals(df)
        assert sig["rsi"] == "overbought"

    def test_oversold_rsi(self):
        n = 250
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        price = 200.0
        close = []
        for i in range(n):
            price -= 1.0 if i % 10 != 0 else -0.5
            close.append(price)
        df = pd.DataFrame({"Date": dates, "Close": close})
        sig = technical.detect_signals(df)
        assert sig["rsi"] == "oversold"
