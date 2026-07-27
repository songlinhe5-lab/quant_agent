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


class KeltnerADXFilter(BaseStrategy):  # noqa: F821 (BaseStrategy 由沙箱 globals 运行时注入)
    """Keltner 通道突破 + ADX 趋势强度过滤 (多头, 稠密类方法契约)。

    本契约同时兼容两条执行路径:
    - batch_backtest_strategy (本地当前代码): 正则要求 class X(BaseStrategy)，_drive_strategy
      检测到 _calculate_indicators/_generate_signals 方法后走稠密契约。
    - optimize_strategy_parameters (含陈旧后端): hasattr 门禁要求这两个实例方法，
      方法存在即通过，无需 Numba 装饰器。

    信号约定 (稠密列 df["signal"]):
        1 = 持有多头 / 0 = 空仓。
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
        self.df = None  # 由引擎注入: strategy_instance.df = df.copy()

    def _calculate_indicators(self):
        df = self.df
        closes = df["close"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        lows = df["low"].values.astype(np.float64)
        n = len(closes)
        ep = self.ema_period
        ap = self.atr_period
        adp = self.adx_period

        # True Range
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        atr = _wilder_smooth(tr, ap)

        # Keltner 中轨: EMA(close)
        ema = np.full(n, np.nan)
        if n > ep:
            alpha = 2.0 / (ep + 1)
            ema[ep - 1] = np.mean(closes[:ep])
            for i in range(ep, n):
                ema[i] = alpha * closes[i] + (1 - alpha) * ema[i - 1]

        # 方向运动 +DM / -DM
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            up = highs[i] - highs[i - 1]
            dn = lows[i - 1] - lows[i]
            plus_dm[i] = up if (up > dn and up > 0) else 0.0
            minus_dm[i] = dn if (dn > up and dn > 0) else 0.0
        tr_sm = _wilder_smooth(tr, adp)
        pdm_sm = _wilder_smooth(plus_dm, adp)
        mdm_sm = _wilder_smooth(minus_dm, adp)
        with np.errstate(divide="ignore", invalid="ignore"):
            plus_di = 100.0 * pdm_sm / tr_sm
            minus_di = 100.0 * mdm_sm / tr_sm
            dx = 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        plus_di = np.nan_to_num(plus_di, nan=0.0)
        minus_di = np.nan_to_num(minus_di, nan=0.0)
        dx = np.nan_to_num(dx, nan=0.0)
        adx = _wilder_smooth(dx, adp)

        upper = ema + self.kc_mult * atr
        lower = ema - self.kc_mult * atr
        self.upper_ = upper
        self.lower_ = lower
        self.adx_ = adx

    def _generate_signals(self):
        df = self.df
        closes = df["close"].values.astype(np.float64)
        upper = self.upper_
        lower = self.lower_
        adx = self.adx_
        th = self.adx_threshold
        n = len(closes)

        sig = np.zeros(n, dtype=np.int32)
        ipos = 0
        for i in range(n):
            if np.isnan(adx[i]) or np.isnan(upper[i]) or np.isnan(lower[i]):
                sig[i] = 1 if ipos else 0
                continue
            if ipos == 0:
                if closes[i] > upper[i] and adx[i] > th:
                    sig[i] = 1
                    ipos = 1
            else:
                if closes[i] < lower[i] or adx[i] < th:
                    sig[i] = 0
                    ipos = 0
                else:
                    sig[i] = 1
        df["signal"] = sig
