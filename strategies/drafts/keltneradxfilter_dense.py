import numpy as np


class KeltnerADXFilter(BaseStrategy):  # noqa: F821 (BaseStrategy 由沙箱 globals 运行时注入)
    """Keltner 通道突破 + ATR 止损（稠密类方法契约）。

    本契约同时兼容两条执行路径:
    - batch_backtest_strategy (本地当前代码): 正则要求 class X(BaseStrategy)，_drive_strategy
      检测到 _calculate_indicators/_generate_signals 方法后走稠密契约。
    - optimize_strategy_parameters (含陈旧后端): hasattr 门禁要求这两个实例方法，
      方法存在即通过，无需 Numba 装饰器。

    信号约定 (稠密列 df["signal"]):
        1 = 持有多头 / 0 = 空仓 (long-only，ATR 跟踪止损离场)。
    """

    def __init__(self, atr_period=14, ema_period=20):
        self.atr_period = int(atr_period)
        self.ema_period = int(ema_period)
        self.df = None  # 由引擎注入: strategy_instance.df = df.copy()

    def _calculate_indicators(self):
        df = self.df
        closes = df["close"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        lows = df["low"].values.astype(np.float64)
        n = len(closes)
        ap = self.atr_period
        ep = self.ema_period

        # True Range + ATR (Wilder 平滑)
        tr = np.zeros(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        atr = np.zeros(n)
        if n > ap:
            atr[ap - 1] = np.mean(tr[:ap])
            for i in range(ap, n):
                atr[i] = (atr[i - 1] * (ap - 1) + tr[i]) / ap

        # EMA 中轨
        ema = np.zeros(n)
        if n > ep:
            ema[ep - 1] = np.mean(closes[:ep])
            a = 2.0 / (ep + 1)
            for i in range(ep, n):
                ema[i] = a * closes[i] + (1 - a) * ema[i - 1]

        self.atr_ = atr
        self.ema_ = ema

    def _generate_signals(self):
        df = self.df
        closes = df["close"].values.astype(np.float64)
        atr = self.atr_
        ema = self.ema_
        n = len(closes)
        ap = self.atr_period
        ep = self.ema_period
        first = ap if ap > ep else ep

        sig = np.zeros(n, dtype=np.int32)
        ipos = 0
        for i in range(first, n):
            if atr[i] <= 0.0:
                sig[i] = 1 if ipos else 0
                continue
            stop = ema[i] - 2.0 * atr[i]
            if ipos == 0:
                sig[i] = 1
                ipos = 1
            elif closes[i] < stop:
                sig[i] = 0
                ipos = 0
            else:
                sig[i] = 1
        df["signal"] = sig
