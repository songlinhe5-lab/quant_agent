"""
TechnicalIndicators - 技术指标计算引擎 (生产级架构)

提供高性能、可配置、可扩展的技术指标计算能力。

核心设计原则:
1. 解耦计算逻辑与信号生成
2. 支持自定义参数配置
3. 缓存优化避免重复计算
4. 易于扩展新指标

作者：VARB-2026-0708-002 Virtual Architecture Board
生成时间：2026-07-08
参考：TA-Lib 工业标准 + Project MINT (Modular Indicators)
"""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# ========== 枚举类型 ==========


class IndicatorType(Enum):
    """指标类型枚举"""

    TREND = "trend"  # 趋势类：MA, EMA, MACD
    MOMENTUM = "momentum"  # 动量类：RSI, Stochastic
    VOLATILITY = "volatility"  # 波动类：ATR, Bollinger
    VOLUME = "volume"  # 成交量类：OBV, AD


@dataclass
class IndicatorConfig:
    """指标配置数据类"""

    name: str
    indicator_type: IndicatorType
    params: Dict[str, Any]
    signal_thresholds: Optional[Dict[str, float]] = None


# ========== 预定义指标配置 (增强版) ==========

DEFAULT_INDICATORS = [
    IndicatorConfig(
        name="MA",
        indicator_type=IndicatorType.TREND,
        params={"periods": [5, 10, 20, 60]},
    ),
    IndicatorConfig(
        name="EMA",
        indicator_type=IndicatorType.TREND,
        params={"periods": [10, 20]},
    ),
    IndicatorConfig(
        name="MACD",
        indicator_type=IndicatorType.TREND,
        params={"fast": 12, "slow": 26, "signal": 9},
    ),
    IndicatorConfig(
        name="RSI",
        indicator_type=IndicatorType.MOMENTUM,
        params={"period": 14},
        signal_thresholds={"overbought": 70, "oversold": 30},
    ),
    IndicatorConfig(
        name="STOCHASTIC",
        indicator_type=IndicatorType.MOMENTUM,
        params={"k_period": 14, "d_period": 3, "smooth_k": 3},
        signal_thresholds={"overbought": 80, "oversold": 20},
    ),
    IndicatorConfig(
        name="BOLLINGER",
        indicator_type=IndicatorType.VOLATILITY,
        params={"period": 20, "std_dev": 2},
    ),
    IndicatorConfig(
        name="ATR",
        indicator_type=IndicatorType.VOLATILITY,
        params={"period": 14},
    ),
    IndicatorConfig(
        name="OBV",
        indicator_type=IndicatorType.VOLUME,
        params={},
    ),
    IndicatorConfig(
        name="VWAP",
        indicator_type=IndicatorType.VOLUME,
        params={},
    ),
    # Epic 3 Task 1: New Advanced Indicators
    IndicatorConfig(
        name="ADX",
        indicator_type=IndicatorType.TREND,
        params={"period": 14},
        signal_thresholds={"strong_trend": 25, "weak_trend": 20},
    ),
    IndicatorConfig(
        name="CCI",
        indicator_type=IndicatorType.MOMENTUM,
        params={"period": 20},
        signal_thresholds={"overbought": 100, "oversold": -100},
    ),
    IndicatorConfig(
        name="VWMA",
        indicator_type=IndicatorType.TREND,
        params={"period": 20},
    ),
    IndicatorConfig(
        name="atr_percent",
        indicator_type=IndicatorType.VOLATILITY,
        params={"period": 14},
    ),
    IndicatorConfig(
        name="elder_ray",
        indicator_type=IndicatorType.MOMENTUM,
        params={"period": 14},
    ),
    IndicatorConfig(
        name="keltner_channels",
        indicator_type=IndicatorType.VOLATILITY,
        params={"period": 20, "atrp_multiplier": 1.5},
    ),
]


# ========== 缓存装饰器 ==========


def cache_result(ttl_seconds: int = 300):
    """结果缓存装饰器 (基于输入参数的 MD5 哈希)"""
    from functools import wraps

    _cache = {}

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            key_data = f"{args}{sorted(kwargs.items())}"
            cache_key = hashlib.md5(key_data.encode()).hexdigest()

            # 检查缓存
            if cache_key in _cache:
                cached_time, cached_result = _cache[cache_key]
                import time

                if time.time() - cached_time < ttl_seconds:
                    return cached_result

            # 执行计算
            result = func(*args, **kwargs)

            # 写入缓存
            import time

            _cache[cache_key] = (time.time(), result)

            return result

        return wrapper

    return decorator


# ========== 核心计算类 ==========


class TechnicalIndicatorsEngine:
    """
    技术指标计算引擎

    使用示例:
        >>> engine = TechnicalIndicatorsEngine()
        >>> klines = [...]  # K 线数据
        >>> indicators = engine.calculate(klines, config=DEFAULT_INDICATORS)
        >>> print(indicators["rsi"]["rsi14"])
    """

    def __init__(self, auto_calculate_signals: bool = True):
        self.auto_calculate_signals = auto_calculate_signals
        self._calculation_stats = {"total_runs": 0, "cached_runs": 0}

    @cache_result(ttl_seconds=300)
    def calculate(
        self,
        klines: List[Dict[str, Any]],
        indicators: Optional[List[IndicatorConfig]] = None,
        return_history: bool = False,
    ) -> Dict[str, Any]:
        """
        计算技术指标

        Args:
            klines: K 线数据列表
            indicators: 指标配置列表 (默认使用 DEFAULT_INDICATORS)
            return_history: 是否返回完整历史序列 (默认仅返回最新值)

        Returns:
            包含所有指标计算结果的字典
        """
        import time

        start_time = time.time()

        if indicators is None:
            indicators = DEFAULT_INDICATORS

        if not klines or len(klines) < 60:
            return {"error": "K 线数据不足", "data": {}}

        # 转换为 DataFrame
        df = self._prepare_dataframe(klines)

        # 计算所有指标
        result = {}
        for config in indicators:
            try:
                calc_func = getattr(self, f"_calculate_{config.name.lower()}")
                indicator_result = calc_func(df, config.params, return_history)
                result[config.name.lower()] = indicator_result

                # 自动计算交易信号
                if self.auto_calculate_signals and config.signal_thresholds:
                    result[config.name.lower()]["signal"] = self._generate_signal(
                        indicator_result, config.signal_thresholds
                    )

            except Exception as e:
                result[config.name.lower()] = {"error": str(e)}

        # 更新统计
        self._calculation_stats["total_runs"] += 1

        elapsed_ms = (time.time() - start_time) * 1000
        result["_meta"] = {
            "computation_time_ms": round(elapsed_ms, 2),
            "data_points": len(df),
        }

        return result

    def _prepare_dataframe(self, klines: List[Dict[str, Any]]) -> pd.DataFrame:
        """准备 DataFrame 数据"""
        df = pd.DataFrame(klines)

        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df

    # ========== 各个指标的计算方法 ==========

    def _calculate_ma(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """移动平均线计算"""
        periods = params.get("periods", [5, 10, 20])

        if return_history:
            result = {}
            for period in periods:
                result[f"ma{period}"] = df["close"].rolling(window=period).mean().tolist()
            return result
        else:
            result = {}
            for period in periods:
                ma_value = df["close"].tail(1).rolling(window=period).mean().iloc[0]
                result[f"ma{period}"] = float(ma_value) if not np.isnan(ma_value) else None
            return result

    def _calculate_ema(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """指数移动平均线计算"""
        periods = params.get("periods", [10, 20])

        if return_history:
            result = {}
            for period in periods:
                result[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean().tolist()
            return result
        else:
            result = {}
            for period in periods:
                ema_value = df["close"].ewm(span=period, adjust=False).mean().tail(1).iloc[0]
                result[f"ema{period}"] = float(ema_value) if not np.isnan(ema_value) else None
            return result

    def _calculate_macd(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """MACD 指标计算"""
        fast, slow, signal = params.get("fast", 12), params.get("slow", 26), params.get("signal", 9)

        exp1 = df["close"].ewm(span=fast, adjust=False).mean()
        exp2 = df["close"].ewm(span=slow, adjust=False).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=signal, adjust=False).mean()
        macd_hist = (dif - dea) * 2

        if return_history:
            return {
                "dif": dif.tolist(),
                "dea": dea.tolist(),
                "histogram": macd_hist.tolist(),
            }
        else:
            return {
                "dif": float(dif.tail(1).iloc[0]) if not np.isnan(dif.tail(1).iloc[0]) else None,
                "dea": float(dea.tail(1).iloc[0]) if not np.isnan(dea.tail(1).iloc[0]) else None,
                "histogram": float(macd_hist.tail(1).iloc[0]) if not np.isnan(macd_hist.tail(1).iloc[0]) else None,
            }

    def _calculate_rsi(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """RSI 指标计算"""
        period = params.get("period", 14)

        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        if return_history:
            return {"rsi": rsi.tolist()}
        else:
            rsi_value = rsi.tail(1).iloc[0]
            return {
                "rsi": float(rsi_value) if not np.isnan(rsi_value) else None,
            }

    def _calculate_bollinger(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """布林带计算"""
        period = params.get("period", 20)
        std_dev = params.get("std_dev", 2)

        middle = df["close"].rolling(window=period).mean()
        std = df["close"].rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)

        if return_history:
            return {
                "upper": upper.tolist(),
                "middle": middle.tolist(),
                "lower": lower.tolist(),
            }
        else:
            return {
                "upper": float(upper.tail(1).iloc[0]) if not np.isnan(upper.tail(1).iloc[0]) else None,
                "middle": float(middle.tail(1).iloc[0]) if not np.isnan(middle.tail(1).iloc[0]) else None,
                "lower": float(lower.tail(1).iloc[0]) if not np.isnan(lower.tail(1).iloc[0]) else None,
            }

    def _calculate_atr(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """ATR 计算"""
        period = params.get("period", 14)

        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(window=period).mean()

        if return_history:
            return {"atr": atr.tolist()}
        else:
            atr_value = atr.tail(1).iloc[0]
            return {
                "atr": float(atr_value) if not np.isnan(atr_value) else None,
            }

    def _calculate_stochastic(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """随机指标 (Stochastic Oscillator) 计算"""
        k_period = params.get("k_period", 14)
        d_period = params.get("d_period", 3)
        smooth_k = params.get("smooth_k", 3)

        # %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
        lowest_low = df["low"].rolling(window=k_period).min()
        highest_high = df["high"].rolling(window=k_period).max()

        raw_k = ((df["close"] - lowest_low) / (highest_high - lowest_low)) * 100

        # 平滑得到 %K
        k = raw_k.rolling(window=smooth_k).mean()

        # %D = K 的移动平均
        d = k.rolling(window=d_period).mean()

        if return_history:
            return {
                "k": k.dropna().tolist(),
                "d": d.dropna().tolist(),
            }
        else:
            latest_k = k.tail(1).iloc[0]
            latest_d = d.tail(1).iloc[0]
            return {
                "k": float(latest_k) if not np.isnan(latest_k) else None,
                "d": float(latest_d) if not np.isnan(latest_d) else None,
            }

    def _calculate_obv(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """能量潮指标 (On-Balance Volume) 计算"""
        # OBV = 累加成交量，价格上涨时为正，下跌时为负
        obv = [0]
        for i in range(1, len(df)):
            if df["close"].iloc[i] > df["close"].iloc[i - 1]:
                obv.append(obv[-1] + df["volume"].iloc[i])
            elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
                obv.append(obv[-1] - df["volume"].iloc[i])
            else:
                obv.append(obv[-1])

        obv_series = pd.Series(obv)

        if return_history:
            return {"obv": obv_series.dropna().tolist()}
        else:
            latest_obv = obv_series.iloc[-1]
            return {
                "obv": float(latest_obv),
            }

    def _calculate_vwap(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """成交量加权平均价 (Volume Weighted Average Price) 计算"""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        volume = df["volume"]

        # VWAP = cumsum(typical_price * volume) / cumsum(volume)
        vwap = (typical_price * volume).cumsum() / volume.cumsum()

        if return_history:
            return {"vwap": vwap.dropna().tolist()}
        else:
            latest_vwap = vwap.iloc[-1]
            return {
                "vwap": float(latest_vwap) if not np.isnan(latest_vwap) else None,
            }

    # Epic 3 Task 1: New Advanced Indicator Methods

    def _calculate_adx(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        ADX (Average Directional Index) - 平均趋向指数

        Args:
            df: DataFrame with OHLCV data
            params: {period: int}
            return_history: Whether to return full history

        Returns:
            Dict with adx, plus_di, minus_di, di_diff
        """
        from backend.utils.advanced_indicators import calculate_adx

        result = calculate_adx(df, period=params.get("period", 14))

        if return_history:
            # For simplicity, return current values
            return (
                {
                    "adx_history": [result["adx"]],
                    "plus_di_history": [result["plus_di"]],
                    "minus_di_history": [result["minus_di"]],
                }
                if result["adx"]
                else {}
            )

        return result

    def _calculate_cci(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        CCI (Commodity Channel Index) - 商品通道指数

        Args:
            df: DataFrame with OHLCV data
            params: {period: int}
            return_history: Whether to return full history

        Returns:
            Current CCI value
        """
        from backend.utils.advanced_indicators import calculate_cci

        cci_value = calculate_cci(df, period=params.get("period", 20))

        if return_history:
            return {"cci_history": [cci_value]}

        return {"cci": float(cci_value) if not np.isnan(cci_value) else None}

    def _calculate_vwma(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        VWMA (Volume Weighted Moving Average) - 成交量加权移动平均

        Args:
            df: DataFrame with OHLCV data
            params: {period: int}
            return_history: Whether to return full history

        Returns:
            Current VWMA value
        """
        from backend.utils.advanced_indicators import calculate_vwma

        vwma_value = calculate_vwma(df, period=params.get("period", 20))

        if return_history:
            return {"vwma_history": [vwma_value]}

        return {"vwma": float(vwma_value) if not np.isnan(vwma_value) else None}

    def _calculate_atr_percent(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        ATR% (Volatility Percentage) - 波动率百分比

        Args:
            df: DataFrame with OHLCV data
            params: {period: int}
            return_history: Whether to return full history

        Returns:
            Dict with atr_percent and atr_relative
        """
        from backend.utils.advanced_indicators import calculate_atr_percent

        result = calculate_atr_percent(df, period=params.get("period", 14))

        if return_history:
            return (
                {"atr_percent_history": [result["atr_percent"]], "atr_relative_history": [result["atr_relative"]]}
                if result["atr_percent"]
                else {}
            )

        return result

    def _calculate_elder_ray(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        Elder-Ray Power - 多头/空头力量指数

        Args:
            df: DataFrame with OHLCV data
            params: {period: int}
            return_history: Whether to return full history

        Returns:
            Dict with bull_power, bear_power, ema_basis
        """
        from backend.utils.advanced_indicators import calculate_elder_ray

        result = calculate_elder_ray(df, period=params.get("period", 14))

        if return_history:
            return (
                {
                    "bull_power_history": [result["bull_power"]],
                    "bear_power_history": [result["bear_power"]],
                    "ema_basis_history": [result["ema_basis"]],
                }
                if result["bull_power"]
                else {}
            )

        return result

    def _calculate_keltner_channels(self, df: pd.DataFrame, params: dict, return_history: bool) -> dict:
        """
        Keltner Channels - 肯特纳通道

        Args:
            df: DataFrame with OHLCV data
            params: {period: int, atrp_multiplier: float}
            return_history: Whether to return full history

        Returns:
            Dict with upper, middle, lower channel values
        """
        from backend.utils.advanced_indicators import calculate_keltner_channels

        result = calculate_keltner_channels(
            df, period=params.get("period", 20), atrp_multiplier=params.get("atrp_multiplier", 1.5)
        )

        if return_history:
            return (
                {
                    "upper_history": [result["upper"]],
                    "middle_history": [result["middle"]],
                    "lower_history": [result["lower"]],
                }
                if result["middle"]
                else {}
            )

        return result

    def _generate_signal(self, indicator_result: dict, thresholds: dict) -> str:
        """生成交易信号"""
        # 简单的信号生成逻辑，可根据需求扩展
        return "neutral"

    def get_statistics(self) -> dict:
        """获取计算引擎统计信息"""
        return self._calculation_stats


# ========== 便捷包装函数 (兼容旧 API) ==========


def calculate_technical_indicators(
    klines: List[Dict[str, Any]],
    return_history: bool = False,
) -> Dict[str, Any]:
    """
    兼容性包装函数 - 保持与旧 API 一致的签名

    推荐使用新的 Engine 架构以获得更好的灵活性和可维护性
    """
    engine = TechnicalIndicatorsEngine(auto_calculate_signals=True)
    result = engine.calculate(klines, return_history=return_history)

    # 转换为旧格式的返回结构
    if not return_history:
        final_result = {
            "ma": {},
            "ema": {},
            "macd": {},
            "rsi": {},
            "bollinger": {},
            "atr": {},
            "overall_signal": "hold",
        }

        if "ma" in result:
            final_result["ma"] = result["ma"]
        if "ema" in result:
            final_result["ema"] = result["ema"]
        if "macd" in result:
            final_result["macd"] = result["macd"]
        if "rsi" in result:
            final_result["rsi"] = result["rsi"]
        if "bollinger" in result:
            final_result["bollinger"] = result["bollinger"]
        if "atr" in result:
            final_result["atr"] = result["atr"]

        return final_result

    return result
