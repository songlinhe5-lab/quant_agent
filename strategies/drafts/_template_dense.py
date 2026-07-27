"""策略草稿模板 (稠密类方法契约) — 复制本文件即可新建策略。

用法:
    1. 复制本文件为 strategies/drafts/<your_strategy>.py (文件名必须全小写)。
    2. 把类名 MyStrategy 改成你的策略名 (保持 class X(BaseStrategy) 形式，
       否则 batch_backtest_strategy 的正则加载会失败)。
    3. 在 __init__ 声明可调参数字典 param_grid 用到的参数。
    4. 在 _calculate_indicators 里算指标 (写入 self.*)，在 _generate_signals
       里产出稠密 signal 列 (写入 df["signal"])。

为什么用这份契约 (而不是裸类 / 模块级函数)?
    - batch_backtest_strategy: 本地进程加载 strategies/drafts/<name>.py，
      正则硬匹配 class X(BaseStrategy)，且 _drive_strategy 检测到
      _calculate_indicators/_generate_signals 方法后走稠密契约。
    - optimize_strategy_parameters: 打到后端 (可能是陈旧后端)，其 hasattr 门禁
      要求实例同时具备 _calculate_indicators 与 _generate_signals 方法，
      否则会报 “Grid Search 仅支持 Numba 矢量化策略”。本模板天然满足。

重要约束:
    - BaseStrategy 不需 import，由沙箱 globals 运行时注入；ruff 会误报 F821，已加 noqa。
    - 列名用小写: df["close"] / df["high"] / df["low"] / df["open"] / df["volume"]
      (引擎会先 _prepare_df 补小写列，但请统一用下划线风格，与 live 策略一致)。
    - 信号列 df["signal"] 为稠密编码:
          1 = 持有多头
          0 = 空仓
         -1 = 持有空头 (如需做空)
      引擎按 entries = signal==1 / exits = signal==0 推演成交。
    - 禁止 for 循环遍历 DataFrame；指标一律用 numpy 矢量化。
    - 沙箱禁止非白名单 import；只允许 numpy / pandas 等数据科学库。
"""

import numpy as np


class MyStrategy(BaseStrategy):  # noqa: F821 (BaseStrategy 由沙箱 globals 运行时注入)
    def __init__(self, fast_period=10, slow_period=20, atr_period=14, atr_multiplier=2.0):
        # 声明可调参数 —— optimize_strategy_parameters 的 param_grid key 必须与此对应
        self.fast_period = int(fast_period)
        self.slow_period = int(slow_period)
        self.atr_period = int(atr_period)
        self.atr_multiplier = float(atr_multiplier)
        self.df = None  # 由引擎注入: strategy_instance.df = df.copy()

    def _calculate_indicators(self):
        """计算指标，结果存到 self.* (不要直接改 df 之外的外部状态)。"""
        df = self.df
        closes = df["close"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        lows = df["low"].values.astype(np.float64)

        # === 示例: 双均线 ===
        fast = _ema(closes, self.fast_period)
        slow = _ema(closes, self.slow_period)

        # === 示例: ATR (Wilder) ===
        atr = _atr(highs, lows, closes, self.atr_period)

        self.fast_ = fast
        self.slow_ = slow
        self.atr_ = atr

    def _generate_signals(self):
        """产出稠密 signal 列 (1=持有多 / 0=空仓 / -1=持有空)。"""
        df = self.df
        closes = df["close"].values.astype(np.float64)
        n = len(closes)

        sig = np.zeros(n, dtype=np.int32)
        ipos = 0  # 0=空仓, 1=持有多
        for i in range(1, n):
            if ipos == 0:
                if self.fast_[i] > self.slow_[i]:  # 金叉入场
                    sig[i] = 1
                    ipos = 1
            else:
                stop = self.slow_[i] - self.atr_multiplier * self.atr_[i]
                if closes[i] < stop:  # ATR 止损离场
                    sig[i] = 0
                    ipos = 0
                else:
                    sig[i] = 1
        df["signal"] = sig


# ============ 下面的矢量化辅助函数可保留，属本文件内部工具 ============
def _ema(values: np.ndarray, period: int) -> np.ndarray:
    n = len(values)
    out = np.zeros(n)
    if n > period:
        out[period - 1] = np.mean(values[:period])
        a = 2.0 / (period + 1)
        for i in range(period, n):
            out[i] = a * values[i] + (1 - a) * out[i - 1]
    return out


def _atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> np.ndarray:
    n = len(closes)
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    out = np.zeros(n)
    if n > period:
        out[period - 1] = np.mean(tr[:period])
        for i in range(period, n):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out
