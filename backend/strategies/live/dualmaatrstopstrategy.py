import numpy as np
import pandas as pd
from typing import Literal

from backend.core.backtest_engine import BaseStrategySandbox as BaseStrategy


class DualMaAtrStopStrategy(BaseStrategy):
    """
    双均线交叉策略（MA10, MA20），带 ATR 动态止损。

    策略逻辑：
    - 当短期均线上穿长期均线时，产生做多信号（signal = 1）。
    - 当短期均线下穿长期均线时，产生做空信号（signal = -1）。
    - 同时计算 ATR 用于底层动态止损：止损价位 = 入场价格 ± ATR × atr_mult。
    - 引擎根据 signal 列执行开仓，并根据 atr 列自动管理止损平仓。

    :param short_window: 短期均线周期，默认 10
    :param long_window: 长期均线周期，默认 20
    :param atr_window: ATR 计算周期，默认 14
    :param atr_mult: ATR 止损倍数，默认 2.0
    :param ma_type: 均线类型，可选 'SMA' 或 'EMA'，默认 'SMA'
    """

    def __init__(
        self,
        short_window: int = 10,
        long_window: int = 30,
        atr_window: int = 21,
        atr_mult: float = 1.6,
        ma_type: Literal["SMA", "EMA"] = "SMA",
    ):
        super().__init__()
        self.short_window = short_window
        self.long_window = long_window
        self.atr_window = atr_window
        self.atr_mult = atr_mult
        self.ma_type = ma_type

    def _calculate_indicators(self):
        """计算技术指标：短期均线、长期均线、ATR。"""
        df = self.df
        # 计算均线
        if self.ma_type == "SMA":
            df["short_ma"] = df["close"].rolling(window=self.short_window).mean()
            df["long_ma"] = df["close"].rolling(window=self.long_window).mean()
        else:  # EMA
            df["short_ma"] = (
                df["close"].ewm(span=self.short_window, adjust=False).mean()
            )  # noqa: E501
            df["long_ma"] = df["close"].ewm(span=self.long_window, adjust=False).mean()

        # 计算 True Range
        prev_close = df["close"].shift(1)
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - prev_close).abs()
        tr3 = (df["low"] - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # 计算 ATR（使用 SMA 或 EMA，此处用 SMA 模拟标准 ATR）
        df["atr"] = true_range.rolling(window=self.atr_window).mean()

    def _generate_signals(self):
        """基于均线交叉生成交易信号，同时保留 ATR 用于止损。"""
        df = self.df
        short_ma = df["short_ma"]
        long_ma = df["long_ma"]

        # 当前交叉状态
        cross_up = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
        cross_down = (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))

        # 生成信号：做多 1，做空 -1，其余为 0
        df["signal"] = np.select([cross_up, cross_down], [1, -1], default=0)
