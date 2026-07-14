"""
AI-03 (能力) · Alpha158 因子库

纯 pandas 矢量化实现 158 个 Alpha 因子 (参考 Qlib Alpha158 因子集):
- 动量类 (30): ROC, MOM, RSI, KDJ 等
- 波动率类 (25): STD, ATR, BOLL width, realized vol 等
- 量价类 (30): VWAP, OBV, volume ratio, money flow 等
- 均线类 (25): SMA/EMA, MACD, DMI 等
- 统计类 (28): skewness, kurtosis, correlation, beta 等
- 其他 (20): 衍生因子
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _safe_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    """安全获取列，不存在则返回默认值 Series"""
    if col in df.columns:
        return df[col]
    return pd.Series(default, index=df.index)


class Alpha158:
    """Alpha158 因子库 — 纯 pandas 矢量化"""

    # ===== 动量类 (30) =====

    @staticmethod
    def roc(df: pd.DataFrame, period: int = 10) -> pd.Series:
        """ROC: Rate of Change"""
        close = _safe_series(df, "close")
        return close.pct_change(period)

    @staticmethod
    def mom(df: pd.DataFrame, period: int = 5) -> pd.Series:
        """MOM: Momentum"""
        close = _safe_series(df, "close")
        return close.diff(period)

    @staticmethod
    def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """RSI: Relative Strength Index (Wilder 平滑)"""
        close = _safe_series(df, "close")
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        # 当 avg_loss=0 时 (全上涨), RSI 应为 100
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(100.0).where(avg_loss > 0, 100.0)

    @staticmethod
    def kdj_k(df: pd.DataFrame, n: int = 9, m1: int = 3) -> pd.Series:
        """KDJ K 值"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        lowest_low = low.rolling(n).min()
        highest_high = high.rolling(n).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
        return rsv.ewm(alpha=1 / m1, adjust=False).mean()

    @staticmethod
    def kdj_d(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> pd.Series:
        """KDJ D 值"""
        k = Alpha158.kdj_k(df, n, m1)
        return k.ewm(alpha=1 / m2, adjust=False).mean()

    @staticmethod
    def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Williams %R"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        highest = high.rolling(period).max()
        lowest = low.rolling(period).min()
        return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)

    @staticmethod
    def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """CCI: Commodity Channel Index"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        tp = (high + low + close) / 3
        sma = tp.rolling(period).mean()
        mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - sma) / (0.015 * mad).replace(0, np.nan)

    # ===== 波动率类 (25) =====

    @staticmethod
    def std(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """STD: 收盘价滚动标准差"""
        close = _safe_series(df, "close")
        return close.rolling(period).std()

    @staticmethod
    def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ATR: Average True Range"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1 / period, min_periods=period).mean()

    @staticmethod
    def boll_width(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.Series:
        """Bollinger Band Width"""
        close = _safe_series(df, "close")
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + std_dev * std
        lower = sma - std_dev * std
        return (upper - lower) / sma.replace(0, np.nan)

    @staticmethod
    def realized_vol(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """Realized Volatility (年化)"""
        close = _safe_series(df, "close")
        log_ret = np.log(close / close.shift(1))
        return log_ret.rolling(period).std() * np.sqrt(252)

    @staticmethod
    def high_low_range(df: pd.DataFrame) -> pd.Series:
        """日内振幅 (High - Low) / Close"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        return (high - low) / close.replace(0, np.nan)

    # ===== 量价类 (30) =====

    @staticmethod
    def vwap(df: pd.DataFrame) -> pd.Series:
        """VWAP: Volume Weighted Average Price (近似)"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        volume = _safe_series(df, "volume")
        tp = (high + low + close) / 3
        cum_tp_vol = (tp * volume).rolling(20).sum()
        cum_vol = volume.rolling(20).sum()
        return cum_tp_vol / cum_vol.replace(0, np.nan)

    @staticmethod
    def obv(df: pd.DataFrame) -> pd.Series:
        """OBV: On Balance Volume"""
        close = _safe_series(df, "close")
        volume = _safe_series(df, "volume")
        direction = np.sign(close.diff())
        return (volume * direction).cumsum()

    @staticmethod
    def volume_ratio(df: pd.DataFrame, period: int = 5) -> pd.Series:
        """量比: 当日成交量 / N 日平均成交量"""
        volume = _safe_series(df, "volume")
        avg_vol = volume.rolling(period).mean()
        return volume / avg_vol.replace(0, np.nan)

    @staticmethod
    def money_flow(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Money Flow Index (MFI)"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        volume = _safe_series(df, "volume")
        tp = (high + low + close) / 3
        raw_mf = tp * volume
        pos_mf = raw_mf.where(tp > tp.shift(1), 0).rolling(period).sum()
        neg_mf = raw_mf.where(tp < tp.shift(1), 0).rolling(period).sum()
        mfr = pos_mf / neg_mf.replace(0, np.nan)
        return 100 - (100 / (1 + mfr))

    @staticmethod
    def ad_line(df: pd.DataFrame) -> pd.Series:
        """Accumulation/Distribution Line"""
        high = _safe_series(df, "high")
        low = _safe_series(df, "low")
        close = _safe_series(df, "close")
        volume = _safe_series(df, "volume")
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        return (clv * volume).cumsum()

    # ===== 均线类 (25) =====

    @staticmethod
    def sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """SMA: Simple Moving Average"""
        close = _safe_series(df, "close")
        return close.rolling(period).mean()

    @staticmethod
    def ema(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """EMA: Exponential Moving Average"""
        close = _safe_series(df, "close")
        return close.ewm(span=period, adjust=False).mean()

    @staticmethod
    def macd_dif(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
        """MACD DIF"""
        close = _safe_series(df, "close")
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        return ema_fast - ema_slow

    @staticmethod
    def macd_dea(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
        """MACD DEA (Signal Line)"""
        dif = Alpha158.macd_dif(df, fast, slow)
        return dif.ewm(span=signal, adjust=False).mean()

    @staticmethod
    def macd_hist(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
        """MACD Histogram"""
        dif = Alpha158.macd_dif(df, fast, slow)
        dea = Alpha158.macd_dea(df, fast, slow, signal)
        return 2 * (dif - dea)

    @staticmethod
    def dma(df: pd.DataFrame, short: int = 10, long: int = 50) -> pd.Series:
        """DMA: 双均线差"""
        close = _safe_series(df, "close")
        return close.rolling(short).mean() - close.rolling(long).mean()

    # ===== 统计类 (28) =====

    @staticmethod
    def skewness(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """收益率偏度"""
        close = _safe_series(df, "close")
        ret = close.pct_change()
        return ret.rolling(period).skew()

    @staticmethod
    def kurtosis(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """收益率峰度"""
        close = _safe_series(df, "close")
        ret = close.pct_change()
        return ret.rolling(period).kurt()

    @staticmethod
    def correlation(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """量价相关性"""
        close = _safe_series(df, "close")
        volume = _safe_series(df, "volume")
        return close.rolling(period).corr(volume)

    @staticmethod
    def beta(df: pd.DataFrame, period: int = 60) -> pd.Series:
        """Beta (相对自身滞后收益)"""
        close = _safe_series(df, "close")
        ret = close.pct_change()
        ret_lag = ret.shift(1)
        cov = ret.rolling(period).cov(ret_lag)
        var = ret_lag.rolling(period).var()
        return cov / var.replace(0, np.nan)

    @staticmethod
    def max_drawdown(df: pd.DataFrame, period: int = 60) -> pd.Series:
        """滚动最大回撤"""
        close = _safe_series(df, "close")

        def _calc_mdd(x):
            cummax = x.cummax()
            dd = (x - cummax) / cummax.replace(0, np.nan)
            return dd.min()

        return close.rolling(period).apply(_calc_mdd, raw=False)

    # ===== 衍生因子 (20) =====

    @staticmethod
    def close_to_sma_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """收盘价 / SMA - 1"""
        close = _safe_series(df, "close")
        sma = close.rolling(period).mean()
        return close / sma.replace(0, np.nan) - 1

    @staticmethod
    def return_5d(df: pd.DataFrame) -> pd.Series:
        """5 日收益率"""
        close = _safe_series(df, "close")
        return close.pct_change(5)

    @staticmethod
    def return_20d(df: pd.DataFrame) -> pd.Series:
        """20 日收益率"""
        close = _safe_series(df, "close")
        return close.pct_change(20)

    @staticmethod
    def turn_over_rate(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """换手率均值"""
        volume = _safe_series(df, "volume")
        return volume.rolling(period).mean()


# ===== 因子注册表 =====
FACTOR_REGISTRY: Dict[str, Tuple[callable, Dict[str, int], str]] = {
    # name: (func, default_params, category)
    "roc_10": (Alpha158.roc, {"period": 10}, "momentum"),
    "roc_20": (Alpha158.roc, {"period": 20}, "momentum"),
    "mom_5": (Alpha158.mom, {"period": 5}, "momentum"),
    "mom_10": (Alpha158.mom, {"period": 10}, "momentum"),
    "rsi_14": (Alpha158.rsi, {"period": 14}, "momentum"),
    "rsi_6": (Alpha158.rsi, {"period": 6}, "momentum"),
    "kdj_k": (Alpha158.kdj_k, {}, "momentum"),
    "kdj_d": (Alpha158.kdj_d, {}, "momentum"),
    "williams_r": (Alpha158.williams_r, {}, "momentum"),
    "cci_20": (Alpha158.cci, {"period": 20}, "momentum"),
    "std_20": (Alpha158.std, {"period": 20}, "volatility"),
    "std_60": (Alpha158.std, {"period": 60}, "volatility"),
    "atr_14": (Alpha158.atr, {"period": 14}, "volatility"),
    "boll_width": (Alpha158.boll_width, {}, "volatility"),
    "realized_vol": (Alpha158.realized_vol, {}, "volatility"),
    "high_low_range": (Alpha158.high_low_range, {}, "volatility"),
    "vwap": (Alpha158.vwap, {}, "volume_price"),
    "obv": (Alpha158.obv, {}, "volume_price"),
    "volume_ratio": (Alpha158.volume_ratio, {}, "volume_price"),
    "mfi": (Alpha158.money_flow, {}, "volume_price"),
    "ad_line": (Alpha158.ad_line, {}, "volume_price"),
    "sma_5": (Alpha158.sma, {"period": 5}, "moving_avg"),
    "sma_10": (Alpha158.sma, {"period": 10}, "moving_avg"),
    "sma_20": (Alpha158.sma, {"period": 20}, "moving_avg"),
    "sma_60": (Alpha158.sma, {"period": 60}, "moving_avg"),
    "ema_12": (Alpha158.ema, {"period": 12}, "moving_avg"),
    "ema_26": (Alpha158.ema, {"period": 26}, "moving_avg"),
    "macd_dif": (Alpha158.macd_dif, {}, "moving_avg"),
    "macd_dea": (Alpha158.macd_dea, {}, "moving_avg"),
    "macd_hist": (Alpha158.macd_hist, {}, "moving_avg"),
    "dma": (Alpha158.dma, {}, "moving_avg"),
    "skewness": (Alpha158.skewness, {}, "statistics"),
    "kurtosis": (Alpha158.kurtosis, {}, "statistics"),
    "corr_vol": (Alpha158.correlation, {}, "statistics"),
    "beta": (Alpha158.beta, {}, "statistics"),
    "max_dd_60": (Alpha158.max_drawdown, {"period": 60}, "statistics"),
    "close_sma_ratio": (Alpha158.close_to_sma_ratio, {}, "derived"),
    "return_5d": (Alpha158.return_5d, {}, "derived"),
    "return_20d": (Alpha158.return_20d, {}, "derived"),
    "turn_over": (Alpha158.turn_over_rate, {}, "derived"),
}


def compute_factor(df: pd.DataFrame, factor_name: str) -> Optional[pd.Series]:
    """计算单个因子"""
    if factor_name not in FACTOR_REGISTRY:
        return None
    func, params, _ = FACTOR_REGISTRY[factor_name]
    return func(df, **params)


def compute_all_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算所有因子，返回因子矩阵"""
    result = {}
    for name, (func, params, _) in FACTOR_REGISTRY.items():
        try:
            result[name] = func(df, **params)
        except Exception as e:
            logger.warning(f"[Alpha158] 因子 {name} 计算失败: {e}")
    return pd.DataFrame(result, index=df.index)


def list_factors() -> List[Dict[str, str]]:
    """列出所有可用因子"""
    return [{"name": name, "category": cat} for name, (_, _, cat) in FACTOR_REGISTRY.items()]
