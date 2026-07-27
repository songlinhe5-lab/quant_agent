import numpy as np


def _calculate_indicators(opens, highs, lows, closes, volumes, p1, p2=0.0):
    """计算 ATR。p1=atr_period, p2 预留未使用。"""
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    atr = np.zeros(n)
    ap = int(p1)
    if n > ap:
        atr[ap - 1] = np.mean(tr[:ap])
        for i in range(ap, n):
            atr[i] = (atr[i - 1] * (ap - 1) + tr[i]) / ap
    return [atr]


def _generate_signals(opens, highs, lows, closes, volumes, indicators, p1, p2):
    """吊灯出场 (Chandelier Exit): 从最高点回撤 mult*ATR 则平仓。"""
    atr = indicators[0]
    n = len(closes)
    sig = np.zeros(n, dtype=np.int32)
    ap = int(p1)
    mult = p2
    if n <= ap:
        return sig
    ipos, hi = False, 0.0
    for i in range(ap, n):
        if not ipos:
            sig[i] = 1
            ipos = True
            hi = highs[i]
        else:
            hi = max(hi, highs[i])
            if lows[i] <= hi - mult * atr[i]:
                sig[i] = -1
                ipos = False
    return sig


class ChandelierExit3ATR(BaseStrategy):  # noqa: F821 (BaseStrategy 由沙箱 globals 运行时注入)
    """吊灯出场策略：多头持有，最高价回撤 mult*ATR 时离场再重新入场。"""

    def __init__(self, atr_period=22, atr_multiplier=3.0):
        self.atr_period = int(atr_period)
        self.atr_multiplier = atr_multiplier

    def generate_signals(self, df):
        df = df.copy()
        op = df["Open"].values.astype(np.float64)
        hi = df["High"].values.astype(np.float64)
        lo = df["Low"].values.astype(np.float64)
        cl = df["Close"].values.astype(np.float64)
        v = df["Volume"].values.astype(np.float64) if "Volume" in df.columns else np.zeros(len(df))
        sig = _generate_signals(
            op,
            hi,
            lo,
            cl,
            v,
            _calculate_indicators(op, hi, lo, cl, v, self.atr_period, 0.0),
            self.atr_period,
            self.atr_multiplier,
        )
        df["position"] = sig
        return df
