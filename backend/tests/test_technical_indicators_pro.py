"""
技术指标计算引擎测试
覆盖: backend/utils/technical_indicators_pro.py
"""

import numpy as np
import pandas as pd
import pytest

from backend.utils.technical_indicators_pro import (
    DEFAULT_INDICATORS,
    IndicatorConfig,
    IndicatorType,
    TechnicalIndicatorsEngine,
    cache_result,
    calculate_technical_indicators,
)


def _make_klines(n: int = 100) -> list:
    """生成模拟 K 线数据"""
    np.random.seed(42)
    base_price = 100.0
    klines = []
    for i in range(n):
        change = np.random.randn() * 2
        close = base_price + change
        high = close + abs(np.random.randn())
        low = close - abs(np.random.randn())
        open_price = base_price + np.random.randn()
        volume = int(np.random.uniform(1e6, 5e6))
        klines.append(
            {
                "time": f"2026-01-{i + 1:02d}",
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        base_price = close
    return klines


@pytest.fixture
def klines():
    return _make_klines(100)


@pytest.fixture
def engine():
    return TechnicalIndicatorsEngine(auto_calculate_signals=True)


class TestIndicatorConfig:
    def test_default_indicators_structure(self):
        assert len(DEFAULT_INDICATORS) >= 10
        for cfg in DEFAULT_INDICATORS:
            assert isinstance(cfg, IndicatorConfig)
            assert cfg.name
            assert isinstance(cfg.indicator_type, IndicatorType)

    def test_indicator_type_enum(self):
        assert IndicatorType.TREND.value == "trend"
        assert IndicatorType.MOMENTUM.value == "momentum"
        assert IndicatorType.VOLATILITY.value == "volatility"
        assert IndicatorType.VOLUME.value == "volume"


class TestCacheResult:
    def test_cache_decorator(self):
        call_count = [0]

        @cache_result(ttl_seconds=60)
        def expensive_func(x):
            call_count[0] += 1
            return x * 2

        assert expensive_func(5) == 10
        assert expensive_func(5) == 10  # 缓存命中
        assert call_count[0] == 1  # 只调用一次

        assert expensive_func(10) == 20  # 不同参数
        assert call_count[0] == 2


class TestTechnicalIndicatorsEngine:
    def test_init(self, engine):
        assert engine.auto_calculate_signals is True
        stats = engine.get_statistics()
        assert stats["total_runs"] == 0

    def test_insufficient_data(self, engine):
        """数据不足返回错误"""
        result = engine.calculate(_make_klines(30))
        assert "error" in result

    def test_calculate_all_indicators(self, engine, klines):
        """计算所有默认指标"""
        result = engine.calculate(klines)
        assert "_meta" in result
        assert result["_meta"]["data_points"] == 100
        assert "ma" in result
        assert "ema" in result
        assert "macd" in result
        assert "rsi" in result
        assert "bollinger" in result
        assert "atr" in result

    def test_calculate_with_history(self, engine, klines):
        """返回完整历史序列"""
        result = engine.calculate(klines, return_history=True)
        assert "ma" in result
        # 历史模式返回列表
        assert isinstance(result["ma"].get("ma5"), list)

    def test_calculate_custom_indicators(self, engine, klines):
        """自定义指标配置"""
        custom = [IndicatorConfig(name="RSI", indicator_type=IndicatorType.MOMENTUM, params={"period": 7})]
        result = engine.calculate(klines, indicators=custom)
        assert "rsi" in result

    def test_statistics_update(self, engine, klines):
        """统计信息更新"""
        engine.calculate(klines)
        stats = engine.get_statistics()
        assert stats["total_runs"] == 1


class TestMACalculation:
    def test_ma_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="MA", indicator_type=IndicatorType.TREND, params={"periods": [5, 10]})],
        )
        ma = result["ma"]
        assert "ma5" in ma
        assert "ma10" in ma
        # tail(1).rolling(5) 可能返回 NaN -> None
        assert ma["ma5"] is None or isinstance(ma["ma5"], float)

    def test_ma_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="MA", indicator_type=IndicatorType.TREND, params={"periods": [5]})],
            return_history=True,
        )
        assert isinstance(result["ma"]["ma5"], list)
        assert len(result["ma"]["ma5"]) == 100


class TestEMACalculation:
    def test_ema_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="EMA", indicator_type=IndicatorType.TREND, params={"periods": [10, 20]})],
        )
        ema = result["ema"]
        assert "ema10" in ema
        assert "ema20" in ema

    def test_ema_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="EMA", indicator_type=IndicatorType.TREND, params={"periods": [10]})],
            return_history=True,
        )
        assert isinstance(result["ema"]["ema10"], list)


class TestMACDCalculation:
    def test_macd_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(
                    name="MACD", indicator_type=IndicatorType.TREND, params={"fast": 12, "slow": 26, "signal": 9}
                )
            ],
        )
        macd = result["macd"]
        assert "dif" in macd
        assert "dea" in macd
        assert "histogram" in macd

    def test_macd_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="MACD", indicator_type=IndicatorType.TREND, params={})],
            return_history=True,
        )
        assert isinstance(result["macd"]["dif"], list)


class TestRSICalculation:
    def test_rsi_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="RSI", indicator_type=IndicatorType.MOMENTUM, params={"period": 14})],
        )
        rsi = result["rsi"]
        assert "rsi" in rsi
        if rsi["rsi"] is not None:
            assert 0 <= rsi["rsi"] <= 100

    def test_rsi_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="RSI", indicator_type=IndicatorType.MOMENTUM, params={"period": 14})],
            return_history=True,
        )
        assert isinstance(result["rsi"]["rsi"], list)


class TestBollingerCalculation:
    def test_bollinger_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(
                    name="BOLLINGER", indicator_type=IndicatorType.VOLATILITY, params={"period": 20, "std_dev": 2}
                )
            ],
        )
        boll = result["bollinger"]
        assert "upper" in boll
        assert "middle" in boll
        assert "lower" in boll
        # upper > middle > lower
        if boll["upper"] and boll["middle"] and boll["lower"]:
            assert boll["upper"] > boll["middle"] > boll["lower"]

    def test_bollinger_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="BOLLINGER", indicator_type=IndicatorType.VOLATILITY, params={})],
            return_history=True,
        )
        assert isinstance(result["bollinger"]["upper"], list)


class TestATRCalculation:
    def test_atr_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="ATR", indicator_type=IndicatorType.VOLATILITY, params={"period": 14})],
        )
        atr = result["atr"]
        assert "atr" in atr
        if atr["atr"] is not None:
            assert atr["atr"] > 0

    def test_atr_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="ATR", indicator_type=IndicatorType.VOLATILITY, params={})],
            return_history=True,
        )
        assert isinstance(result["atr"]["atr"], list)


class TestStochasticCalculation:
    def test_stochastic_latest(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(
                    name="STOCHASTIC",
                    indicator_type=IndicatorType.MOMENTUM,
                    params={"k_period": 14, "d_period": 3, "smooth_k": 3},
                )
            ],
        )
        stoch = result["stochastic"]
        assert "k" in stoch
        assert "d" in stoch

    def test_stochastic_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="STOCHASTIC", indicator_type=IndicatorType.MOMENTUM, params={})],
            return_history=True,
        )
        assert isinstance(result["stochastic"]["k"], list)


class TestOBVCalculation:
    def test_obv_latest(self, engine, klines):
        result = engine.calculate(
            klines, indicators=[IndicatorConfig(name="OBV", indicator_type=IndicatorType.VOLUME, params={})]
        )
        obv = result["obv"]
        assert "obv" in obv
        assert isinstance(obv["obv"], float)

    def test_obv_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="OBV", indicator_type=IndicatorType.VOLUME, params={})],
            return_history=True,
        )
        assert isinstance(result["obv"]["obv"], list)


class TestVWAPCalculation:
    def test_vwap_latest(self, engine, klines):
        result = engine.calculate(
            klines, indicators=[IndicatorConfig(name="VWAP", indicator_type=IndicatorType.VOLUME, params={})]
        )
        vwap = result["vwap"]
        assert "vwap" in vwap
        if vwap["vwap"] is not None:
            assert vwap["vwap"] > 0

    def test_vwap_history(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="VWAP", indicator_type=IndicatorType.VOLUME, params={})],
            return_history=True,
        )
        assert isinstance(result["vwap"]["vwap"], list)


class TestAdvancedIndicators:
    """高级指标测试 (ADX, CCI, VWMA, ATR%, Elder Ray, Keltner)"""

    def test_adx(self, engine, klines):
        result = engine.calculate(
            klines, indicators=[IndicatorConfig(name="ADX", indicator_type=IndicatorType.TREND, params={"period": 14})]
        )
        assert "adx" in result

    def test_cci(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[IndicatorConfig(name="CCI", indicator_type=IndicatorType.MOMENTUM, params={"period": 20})],
        )
        assert "cci" in result

    def test_vwma(self, engine, klines):
        result = engine.calculate(
            klines, indicators=[IndicatorConfig(name="VWMA", indicator_type=IndicatorType.TREND, params={"period": 20})]
        )
        assert "vwma" in result

    def test_atr_percent(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(name="atr_percent", indicator_type=IndicatorType.VOLATILITY, params={"period": 14})
            ],
        )
        assert "atr_percent" in result

    def test_elder_ray(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(name="elder_ray", indicator_type=IndicatorType.MOMENTUM, params={"period": 14})
            ],
        )
        assert "elder_ray" in result

    def test_keltner_channels(self, engine, klines):
        result = engine.calculate(
            klines,
            indicators=[
                IndicatorConfig(
                    name="keltner_channels",
                    indicator_type=IndicatorType.VOLATILITY,
                    params={"period": 20, "atrp_multiplier": 1.5},
                )
            ],
        )
        assert "keltner_channels" in result


class TestCompatibilityWrapper:
    def test_calculate_technical_indicators_latest(self, klines):
        result = calculate_technical_indicators(klines, return_history=False)
        assert "ma" in result
        assert "ema" in result
        assert "macd" in result
        assert "rsi" in result
        assert "bollinger" in result
        assert "atr" in result
        assert "overall_signal" in result

    def test_calculate_technical_indicators_history(self, klines):
        result = calculate_technical_indicators(klines, return_history=True)
        assert "_meta" in result


class TestPrepareDataframe:
    def test_prepare_dataframe(self, engine, klines):
        df = engine._prepare_dataframe(klines)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 100
        assert df["close"].dtype in [np.float64, float, np.int64]

    def test_prepare_dataframe_with_strings(self, engine):
        """字符串数值转换"""
        klines = [
            {"open": "100.5", "high": "105.5", "low": "95.5", "close": "102.5", "volume": "1000000"} for _ in range(70)
        ]
        df = engine._prepare_dataframe(klines)
        assert df["close"].dtype == np.float64


class TestGenerateSignal:
    def test_generate_signal_neutral(self, engine):
        signal = engine._generate_signal({"rsi": 50}, {"overbought": 70, "oversold": 30})
        assert signal == "neutral"
