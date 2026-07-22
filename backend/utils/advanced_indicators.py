"""
Epic 3 Task 1: 高级技术指标实现 (Advanced Indicators)

新增指标：
- ADX/DMI: 趋势强度指数
- CCI: 商品通道指数
- VWMA: 成交量加权移动平均
- ATR%: 波动率百分比
- Elder-Ray: 多空力量指数
- Keltner Channels: 肯特纳通道
"""

import numpy as np
import pandas as pd


def calculate_true_range(df: pd.DataFrame) -> pd.Series:
    """计算真实波幅序列"""
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr1 = high - low
    tr2 = abs(high - close_prev)
    tr3 = abs(low - close_prev)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr


def smooth_ema(series: pd.Series, period: int) -> pd.Series:
    """使用 Wilder's smoothing (类似 EMA)"""
    return series.ewm(span=period, adjust=False).mean()


def where(condition, x, y):
    """条件选择 (类似 NumPy where)"""
    return condition.where(condition, y) if hasattr(condition, "where") else np.where(condition, x, y)


# ========== ADX/DMI Implementation (Fixed Version) ==========


def calculate_adx(df: pd.DataFrame, period: int = 14) -> dict:
    """
    ADX (Average Directional Index) - 平均趋向指数

    Args:
        df: OHLCV DataFrame
        period: 计算周期

    Returns:
        Dict with adx, plus_di, minus_di, di_diff
    """
    high = df["high"]
    low = df["low"]

    # Calculate +/- DM using vectorized operations
    plus_dm_raw = high.diff().values
    minus_dm_raw = -low.diff().values

    mask_plus = (plus_dm_raw > minus_dm_raw) & (plus_dm_raw > 0)
    mask_minus = (minus_dm_raw > plus_dm_raw) & (minus_dm_raw > 0)

    plus_dm = np.where(mask_plus, plus_dm_raw, 0.0)
    minus_dm = np.where(mask_minus, minus_dm_raw, 0.0)

    # Convert back to Series for smoothing
    plus_dm_series = pd.Series(plus_dm, index=df.index)
    minus_dm_series = pd.Series(minus_dm, index=df.index)

    # TR for denominator (using ATR internally)
    tr = calculate_true_range(df)
    atr_series = smooth_ema(tr, period)
    atr_value = atr_series.iloc[-1] if not np.isnan(atr_series.iloc[-1]) else None

    if not atr_value or atr_value == 0:
        return {
            "adx": None,
            "plus_di": None,
            "minus_di": None,
            "di_diff": None,
        }

    # Calculate DI using absolute values
    smooth_plus_dm = smooth_ema(abs(plus_dm_series), period)
    smooth_minus_dm = smooth_ema(abs(minus_dm_series), period)

    plus_di = 100 * smooth_plus_dm / atr_series
    minus_di = 100 * smooth_minus_dm / atr_series

    # DX (Directional Movement Index)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)

    # ADX (EMA of DX)
    adx_values = smooth_ema(dx, period)
    adx = adx_values.iloc[-1]

    return {
        "adx": float(adx) if not np.isnan(adx) else None,
        "plus_di": float(plus_di.iloc[-1]) if not np.isnan(plus_di.iloc[-1]) else None,
        "minus_di": float(minus_di.iloc[-1]) if not np.isnan(minus_di.iloc[-1]) else None,
        "di_diff": float(abs(plus_di.iloc[-1] - minus_di.iloc[-1]))
        if not np.isnan(plus_di.iloc[-1] - minus_di.iloc[-1])
        else None,
    }


# ========== CCI Implementation ==========


def calculate_cci(df: pd.DataFrame, period: int = 20) -> float:
    """
    CCI (Commodity Channel Index) - 商品通道指数

    Args:
        df: OHLCV DataFrame
        period: 计算周期

    Returns:
        Current CCI value
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3

    # SMA of TP
    sma = typical_price.rolling(window=period).mean()

    # Mean Deviation
    mean_dev = typical_price.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)

    # CCI formula
    cci = (typical_price - sma) / (0.015 * mean_dev)

    return cci.iloc[-1]


# ========== VWMA Implementation ==========


def calculate_vwma(df: pd.DataFrame, period: int = 20) -> float:
    """
    VWMA (Volume Weighted Moving Average) - 成交量加权移动平均

    Args:
        df: OHLCV DataFrame
        period: 计算周期

    Returns:
        Current VWMA value
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3

    vwma = (typical_price * df["volume"]).rolling(window=period).sum() / df["volume"].rolling(window=period).sum()

    return vwma.iloc[-1]


# ========== ATR% Implementation ==========


def calculate_atr_percent(df: pd.DataFrame, period: int = 14) -> dict:
    """
    ATR% (Volatility Percentage) - 波动率百分比

    Args:
        df: OHLCV DataFrame
        period: 计算周期

    Returns:
        Dict with atr_percent and atr_relative
    """
    tr = calculate_true_range(df)
    atr_series = smooth_ema(tr, period)
    atr_value = atr_series.iloc[-1]

    current_price = df["close"].iloc[-1]

    if current_price and current_price != 0:
        return {
            "atr_percent": float((atr_value / abs(current_price)) * 100),
            "atr_relative": float(atr_value / abs(current_price)),
        }

    return {"atr_percent": None, "atr_relative": None}


# ========== Elder-Ray Implementation ==========


def calculate_elder_ray(df: pd.DataFrame, period: int = 14) -> dict:
    """
    Elder-Ray Power - 多头/空头力量

    Args:
        df: OHLCV DataFrame
        period: EMA 周期

    Returns:
        Dict with bull_power, bear_power, ema_basis
    """
    ema = df["close"].ewm(span=period, adjust=False).mean()

    current_high = df["high"].iloc[-1]
    current_low = df["low"].iloc[-1]
    current_ema = ema.iloc[-1]

    return {
        "bull_power": float(current_high - current_ema) if not np.isnan(current_high - current_ema) else None,
        "bear_power": float(current_low - current_ema) if not np.isnan(current_low - current_ema) else None,
        "ema_basis": float(current_ema) if not np.isnan(current_ema) else None,
    }


# ========== Keltner Channels Implementation ==========


def calculate_keltner_channels(df: pd.DataFrame, period: int = 20, atrp_multiplier: float = 1.5) -> dict:
    """
    Keltner Channels - 肯特纳通道

    Args:
        df: OHLCV DataFrame
        period: EMA period
        atrp_multiplier: ATR multiplier (typically 1.5 or 2.0)

    Returns:
        Dict with upper, middle, lower channel values
    """
    # Middle line (EMA)
    ema = df["close"].ewm(span=period, adjust=False).mean()

    # Calculate ATR directly (same formula as in engine._calculate_atr)
    high_low = df["high"] - df["low"]
    high_close = abs(df["high"] - df["close"].shift())
    low_close = abs(df["low"] - df["close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr = true_range.rolling(window=period).mean()

    atr_value = atr.iloc[-1] if not np.isnan(atr.iloc[-1]) else None

    middle = ema.iloc[-1]

    if not atr_value or atr_value == 0:
        return {
            "upper": None,
            "middle": float(middle) if not np.isnan(middle) else None,
            "lower": None,
        }

    upper = middle + (atrp_multiplier * atr_value)
    lower = middle - (atrp_multiplier * atr_value)

    channel_width = ((upper - lower) / middle * 100) if (upper and lower and middle and middle != 0) else None

    return {
        "upper": float(upper) if not np.isnan(upper) else None,
        "middle": float(middle) if not np.isnan(middle) else None,
        "lower": float(lower) if not np.isnan(lower) else None,
        "channel_width": float(channel_width) if not np.isnan(channel_width) else None,
    }
