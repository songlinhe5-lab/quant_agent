import numpy as np


def _wilder_smooth(arr: np.ndarray, period: int) -> np.ndarray:
    """Wilder 平滑 (RMA): 首值为 period 窗口均值，其后按 (prev*(p-1)+x)/p 递归。"""
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return out
    out[period - 1] = np.mean(arr[:period])
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + arr[i]) / period
    return out


def _calc_kc_adx(opens, highs, lows, closes, ema_period, atr_period, kc_mult, adx_period):
    """返回 (atr, ema, upper, lower, adx)。"""
    n = len(closes)

    # True Range & ATR (Wilder)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = _wilder_smooth(tr, atr_period)

    # Keltner 中轨: EMA(close)
    ema = np.full(n, np.nan)
    if n > ema_period:
        alpha = 2.0 / (ema_period + 1)
        ema[ema_period - 1] = np.mean(closes[:ema_period])
        for i in range(ema_period, n):
            ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]

    # 方向运动 +DM / -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0

    tr_sm = _wilder_smooth(tr, adx_period)
    pdm_sm = _wilder_smooth(plus_dm, adx_period)
    mdm_sm = _wilder_smooth(minus_dm, adx_period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * pdm_sm / tr_sm
        minus_di = 100.0 * mdm_sm / tr_sm
        dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    plus_di = np.nan_to_num(plus_di, nan=0.0)
    minus_di = np.nan_to_num(minus_di, nan=0.0)
    dx = np.nan_to_num(dx, nan=0.0)
    adx = _wilder_smooth(dx, adx_period)

    upper = ema + kc_mult * atr
    lower = ema - kc_mult * atr
    return atr, ema, upper, lower, adx


def _generate_kc_adx_signals(opens, highs, lows, closes, upper, lower, adx, adx_threshold):
    n = len(closes)
    sig = np.zeros(n, dtype=np.int32)
    ipos = False
    for i in range(n):
        if np.isnan(adx[i]) or np.isnan(upper[i]) or np.isnan(lower[i]):
            continue
        if not ipos:
            if closes[i] > upper[i] and adx[i] > adx_threshold:
                sig[i] = 1
                ipos = True
        else:
            # 离场: 跌破 KC 下轨，或趋势强度衰减至阈值以下
            if closes[i] < lower[i] or adx[i] < adx_threshold:
                sig[i] = -1
                ipos = False
    return sig


class KeltnerADXFilter(BaseStrategy):  # noqa: F821 (BaseStrategy 由沙箱 globals 运行时注入)
    """Keltner 通道突破 + ADX 趋势强度过滤 (多头)。

    入场: close 上穿 KC 上轨 且 ADX > adx_threshold (趋势有效)
    离场: close 跌破 KC 下轨 或 ADX < adx_threshold (趋势衰竭)
    """

    def __init__(
        self,
        ema_period=20,
        atr_period=14,
        kc_mult=2.0,
        adx_period=14,
        adx_threshold=25.0,
    ):
        self.ema_period = int(ema_period)
        self.atr_period = int(atr_period)
        self.kc_mult = float(kc_mult)
        self.adx_period = int(adx_period)
        self.adx_threshold = float(adx_threshold)

    def generate_signals(self, df):
        df = df.copy()
        op = df["Open"].values.astype(np.float64)
        hi = df["High"].values.astype(np.float64)
        lo = df["Low"].values.astype(np.float64)
        cl = df["Close"].values.astype(np.float64)
        atr, ema, upper, lower, adx = _calc_kc_adx(
            op, hi, lo, cl, self.ema_period, self.atr_period, self.kc_mult, self.adx_period
        )
        sig = _generate_kc_adx_signals(op, hi, lo, cl, upper, lower, adx, self.adx_threshold)
        df["position"] = sig
        return df
