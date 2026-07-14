"""
QUANT-03: 复杂横截面选股引擎

纯 Pandas 矢量化技术指标计算 + 安全表达式解析求值。
支持 RSI(14) > KDJ.K 等跨指标组合表达式。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 技术指标计算 (纯 pandas 矢量化)
# ─────────────────────────────────────────────


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI — Wilder 平滑法 (EMA 递归)"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _kdj(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ 随机指标 — 返回 (K, D, J)"""
    lowest_low = low.rolling(n, min_periods=n).min()
    highest_high = high.rolling(n, min_periods=n).max()
    denom = highest_high - lowest_low
    rsv = ((close - lowest_low) / denom.replace(0, np.nan)) * 100.0
    k = rsv.ewm(alpha=1.0 / m1, min_periods=1, adjust=False).mean()
    d = k.ewm(alpha=1.0 / m2, min_periods=1, adjust=False).mean()
    j = 3.0 * k - 2.0 * d
    return k, d, j


def _macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD — 返回 (DIF, DEA, histogram)"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = 2.0 * (dif - dea)
    return dif, dea, histogram


def _bollinger(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """布林带 — 返回 (upper, mid, lower)"""
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ATR — Average True Range"""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def _volume_ratio(volume: pd.Series, period: int = 5) -> pd.Series:
    """量比: 当日成交量 / 过去 N 日均量"""
    avg_vol = volume.rolling(period, min_periods=period).mean()
    return volume / avg_vol.replace(0, np.nan)


# ─────────────────────────────────────────────
# 指标注册表
# ─────────────────────────────────────────────

# 指标名 → (计算函数, 输出列名列表)
_INDICATOR_REGISTRY: Dict[str, tuple] = {}


def _register(name: str, func, output_cols: List[str]):
    _INDICATOR_REGISTRY[name] = (func, output_cols)


_register("RSI", lambda df, p=14: _rsi(df["close"], p), ["rsi"])
_register("KDJ", lambda df, n=9: _kdj(df["high"], df["low"], df["close"], n), ["kdj_k", "kdj_d", "kdj_j"])
_register("MACD", lambda df, f=12, s=26, sig=9: _macd(df["close"], f, s, sig), ["macd_dif", "macd_dea", "macd_histogram"])
_register("BOLL", lambda df, p=20: _bollinger(df["close"], p), ["boll_upper", "boll_mid", "boll_lower"])
_register("ATR", lambda df, p=14: _atr(df["high"], df["low"], df["close"], p), ["atr"])
_register("VOL_RATIO", lambda df, p=5: _volume_ratio(df["volume"], p), ["vol_ratio"])
# SMA/EMA 在 compute_indicators 中单独处理 (参数化列名)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算全部技术指标，将结果附加到 DataFrame 副本。

    要求 df 包含列: open, high, low, close, volume (小写)。
    返回附加了 rsi, kdj_k, kdj_d, kdj_j, macd_dif, macd_dea, macd_histogram,
    boll_upper, boll_mid, boll_lower, atr, vol_ratio, sma_5/10/20/60, ema_12/26 的 DataFrame。
    """
    result = df.copy()
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(set(result.columns)):
        missing = required - set(result.columns)
        raise ValueError(f"DataFrame 缺少必要列: {missing}")

    # 基础指标
    for name, (func, cols) in _INDICATOR_REGISTRY.items():
        if name in ("SMA", "EMA"):
            continue  # 特殊处理
        outputs = func(result)
        if not isinstance(outputs, tuple):
            outputs = (outputs,)
        for col, val in zip(cols, outputs):
            result[col] = val

    # SMA 系列
    for p in [5, 10, 20, 60]:
        result[f"sma_{p}"] = result["close"].rolling(p, min_periods=p).mean()

    # EMA 系列
    for p in [12, 26]:
        result[f"ema_{p}"] = result["close"].ewm(span=p, adjust=False).mean()

    return result


# ─────────────────────────────────────────────
# 安全表达式解析器
# ─────────────────────────────────────────────

# 允许的指标引用: RSI, KDJ.K, KDJ.D, KDJ.J, MACD.dif, MACD.dea, MACD.histogram,
# BOLL.upper, BOLL.mid, BOLL.lower, ATR, VOL_RATIO, SMA_5, SMA_10, SMA_20, SMA_60, EMA_12, EMA_26
_ALLOWED_INDICATORS = frozenset({
    "rsi", "kdj_k", "kdj_d", "kdj_j",
    "macd_dif", "macd_dea", "macd_histogram",
    "boll_upper", "boll_mid", "boll_lower",
    "atr", "vol_ratio",
    "sma_5", "sma_10", "sma_20", "sma_60",
    "ema_12", "ema_26",
})

# 表达式中允许的用户友好名称 → DataFrame 列名映射
_EXPR_COL_MAP = {
    "RSI": "rsi",
    "KDJ.K": "kdj_k", "KDJ.D": "kdj_d", "KDJ.J": "kdj_j",
    "MACD.DIF": "macd_dif", "MACD.DEA": "macd_dea", "MACD.HISTOGRAM": "macd_histogram",
    "MACD.HIST": "macd_histogram",
    "BOLL.UPPER": "boll_upper", "BOLL.MID": "boll_mid", "BOLL.LOWER": "boll_lower",
    "ATR": "atr", "VOL_RATIO": "vol_ratio",
}

# 安全 token 白名单正则
_TOKEN_RE = re.compile(
    r"^(?:RSI|KDJ|MACD|BOLL|ATR|VOL_RATIO|SMA|EMA)(?:\.\w+)?(?:\(\d+\))?$"
    r"|^[<>!=]=?$"
    r"|^(?:AND|OR|NOT|and|or|not)$"
    r"|^[0-9]+(?:\.[0-9]+)?$"
    r"|^[()]+$"
    r"|^[-+*/]$"
)


def _normalize_expr(expr: str) -> str:
    """
    将用户表达式转换为 pandas 可 eval 的形式。

    例: "RSI(14) > KDJ.K AND MACD.histogram > 0"
      → "rsi > kdj_k and macd_histogram > 0"
    """
    normalized = expr.strip()

    # 替换 MACD.histogram → MACD.HISTOGRAM (统一大写)
    normalized = re.sub(r"MACD\.histogram", "MACD.HISTOGRAM", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"MACD\.hist\b", "MACD.HISTOGRAM", normalized, flags=re.IGNORECASE)

    # 替换带参数的指标调用: RSI(14) → rsi (忽略参数，使用默认)
    for ind_name in ["RSI", "KDJ", "MACD", "BOLL", "ATR", "VOL_RATIO"]:
        normalized = re.sub(
            rf"\b{ind_name}\(\d+\)", ind_name, normalized, flags=re.IGNORECASE
        )

    # 替换 SMA(n) / EMA(n) → sma_n / ema_n
    normalized = re.sub(r"\bSMA\((\d+)\)", r"sma_\1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bEMA\((\d+)\)", r"ema_\1", normalized, flags=re.IGNORECASE)

    # 替换用户友好名 → DataFrame 列名
    for user_name, col_name in _EXPR_COL_MAP.items():
        normalized = re.sub(rf"\b{re.escape(user_name)}\b", col_name, normalized, flags=re.IGNORECASE)

    # 逻辑运算符统一为小写
    normalized = re.sub(r"\bAND\b", "and", normalized)
    normalized = re.sub(r"\bOR\b", "or", normalized)
    normalized = re.sub(r"\bNOT\b", "not", normalized)

    return normalized


def _validate_expression(normalized: str) -> None:
    """白名单校验：确保表达式只包含允许的 token"""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.]*|[<>!=]=?|[()]|[0-9]+(?:\.[0-9]+)?|[-+*/]", normalized)
    for token in tokens:
        if token in ("and", "or", "not"):
            continue
        if token in (">", "<", ">=", "<=", "==", "!=", "+", "-", "*", "/"):
            continue
        if token in ("(", ")"):
            continue
        if re.match(r"^[0-9]+(?:\.[0-9]+)?$", token):
            continue
        if token in _ALLOWED_INDICATORS:
            continue
        raise ValueError(f"非法 token: '{token}'。仅允许: {sorted(_ALLOWED_INDICATORS)}")


def evaluate_expression(df: pd.DataFrame, expr: str) -> pd.Series:
    """
    对 DataFrame 求值表达式，返回布尔 Series。

    Args:
        df: 已调用 compute_indicators() 的 DataFrame
        expr: 用户表达式，如 "RSI(14) < 30 AND MACD.histogram > 0"

    Returns:
        pd.Series[bool]: 每行是否满足条件
    """
    normalized = _normalize_expr(expr)
    _validate_expression(normalized)
    try:
        result = df.eval(normalized)
    except Exception as e:
        raise ValueError(f"表达式求值失败: {e} (normalized: {normalized})") from e
    return result.astype(bool)


# ─────────────────────────────────────────────
# 横截面筛选入口
# ─────────────────────────────────────────────


def screen(
    symbols: List[str],
    expression: str,
    kline_data: Dict[str, pd.DataFrame],
) -> Dict[str, Any]:
    """
    横截面筛选：对每只标的计算指标并评估表达式。

    Args:
        symbols: 标的代码列表
        expression: 跨指标表达式
        kline_data: {symbol: DataFrame(含 OHLCV 小写列)}

    Returns:
        {passed: [{symbol, indicators}], failed_count}
    """
    passed = []
    failed_count = 0

    for sym in symbols:
        df = kline_data.get(sym)
        if df is None or len(df) < 30:
            failed_count += 1
            continue
        try:
            enriched = compute_indicators(df)
            mask = evaluate_expression(enriched, expression)
            if mask.iloc[-1]:
                # 取最新一行的指标值
                latest = enriched.iloc[-1]
                indicator_snapshot = {
                    "rsi": round(latest.get("rsi", 0) or 0, 2),
                    "kdj_k": round(latest.get("kdj_k", 0) or 0, 2),
                    "kdj_d": round(latest.get("kdj_d", 0) or 0, 2),
                    "kdj_j": round(latest.get("kdj_j", 0) or 0, 2),
                    "macd_dif": round(latest.get("macd_dif", 0) or 0, 4),
                    "macd_dea": round(latest.get("macd_dea", 0) or 0, 4),
                    "macd_histogram": round(latest.get("macd_histogram", 0) or 0, 4),
                    "atr": round(latest.get("atr", 0) or 0, 4),
                    "vol_ratio": round(latest.get("vol_ratio", 0) or 0, 2),
                }
                passed.append({"symbol": sym, "indicators": indicator_snapshot})
            else:
                failed_count += 1
        except Exception as e:
            logger.warning(f"[CrossSectional] {sym} 计算失败: {e}")
            failed_count += 1

    return {"passed": passed, "failed_count": failed_count}
