"""YFinance 技术指标计算（复制自 backend.services.yfinance.technical，物理解耦，零 backend 依赖）"""

from typing import Dict, List

import pandas as pd

PERIOD_RANGES = {
    "1d": ("1d", "5m"),
    "5d": ("5d", "15m"),
    "1mo": ("1mo", "1h"),
    "3mo": ("3mo", "1d"),
    "6mo": ("6mo", "1d"),
    "1y": ("1y", "1d"),
    "2y": ("2y", "1d"),
    "5y": ("5y", "1d"),
    "10y": ("10y", "1d"),
    "ytd": ("ytd", "1d"),
    "max": ("max", "1d"),
}

VALID_INDICATORS = {"MACD", "RSI", "EMA", "SMA"}


def resolve_period_range(period: str) -> tuple:
    if period not in PERIOD_RANGES:
        raise ValueError(f"不支持的周期: {period}。支持的周期有: {list(PERIOD_RANGES.keys())}")
    return PERIOD_RANGES[period]


def calculate_technical_indicators(df: pd.DataFrame, indicators: List[str] = None) -> Dict:
    """计算技术指标（MACD/RSI/EMA/SMA），矢量化操作。"""
    if df is None or df.empty:
        return {}

    df = df.copy()
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")

    df = df.sort_index()
    close = df["Close"]

    results: Dict = {}

    target = indicators or ["MACD", "RSI", "EMA", "SMA"]

    if "SMA" in target:
        sma_windows = [20, 50, 200]
        for w in sma_windows:
            if len(close) >= w:
                sma = close.rolling(window=w).mean()
                results[f"SMA_{w}"] = [None if pd.isna(v) else round(float(v), 4) for v in sma]

    if "EMA" in target:
        ema_windows = [12, 26]
        for w in ema_windows:
            if len(close) >= w:
                ema = close.ewm(span=w, adjust=False).mean()
                results[f"EMA_{w}"] = [None if pd.isna(v) else round(float(v), 4) for v in ema]

    if "RSI" in target:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=14).mean()
        avg_loss = loss.rolling(window=14).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        rsi = 100 - (100 / (1 + rs))
        results["RSI_14"] = [None if pd.isna(v) else round(float(v), 2) for v in rsi]

    if "MACD" in target:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        results["MACD"] = {
            "macd": [None if pd.isna(v) else round(float(v), 4) for v in macd_line],
            "signal": [None if pd.isna(v) else round(float(v), 4) for v in signal_line],
            "hist": [None if pd.isna(v) else round(float(v), 4) for v in hist],
        }

    return results


def detect_signals(df: pd.DataFrame) -> Dict:
    """基于技术指标生成买卖信号。"""
    signals = {"macd": "neutral", "rsi": "neutral", "trend": "neutral"}

    if df is None or df.empty:
        return signals

    close = df["Close"]

    # 趋势
    if len(close) >= 200:
        sma50 = close.rolling(50).mean().iloc[-1]
        sma200 = close.rolling(200).mean().iloc[-1]
        if pd.notna(sma50) and pd.notna(sma200):
            if sma50 > sma200:
                signals["trend"] = "bullish"
            elif sma50 < sma200:
                signals["trend"] = "bearish"

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    last_rsi = rsi.iloc[-1]
    if pd.notna(last_rsi):
        if last_rsi > 70:
            signals["rsi"] = "overbought"
        elif last_rsi < 30:
            signals["rsi"] = "oversold"

    return signals
