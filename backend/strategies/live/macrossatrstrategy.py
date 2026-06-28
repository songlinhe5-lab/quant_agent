from typing import Literal

import pandas as pd

from backend.core.backtest_engine import BaseStrategySandbox as BaseStrategy


class MaCrossAtrStrategy(BaseStrategy):
    """
    双均线(MA10, MA20)交叉策略，带2.0倍ATR动态止损。

    策略逻辑：
    1. 计算快慢均线（fast_ma, slow_ma）。
    2. 当快线上穿慢线时产生做多信号（signal=1）。
    3. 当快线下穿慢线时产生做空信号（signal=-1）。
    4. 计算ATR（Average True Range）用于底层动态止损。

    :param fast_ma: int, 快线均线周期，默认10
    :param slow_ma: int, 慢线均线周期，默认20
    :param atr_period: int, ATR计算周期，默认14
    :param atr_mult: float, ATR止损倍数，默认2.0
    :param ma_type: Literal, 均线计算类型，默认SMA
    """

    def __init__(
        self,
        fast_ma: int = 10,
        slow_ma: int = 20,
        atr_period: int = 14,
        atr_mult: float = 2.0,
        ma_type: Literal["SMA", "EMA"] = "SMA",
    ):
        super().__init__()
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.ma_type = ma_type
        self.df = pd.DataFrame()  # 💡 显式声明 df 属性，消除静态类型检查器的报错

    def _calculate_indicators(self):
        """计算技术指标：快线、慢线均线和ATR"""
        # 均线
        if self.ma_type == "EMA":
            self.df["ma_fast"] = (
                self.df["close"].ewm(span=self.fast_ma, adjust=False).mean()
            )  # noqa: E501
            self.df["ma_slow"] = (
                self.df["close"].ewm(span=self.slow_ma, adjust=False).mean()
            )  # noqa: E501
        else:
            self.df["ma_fast"] = self.df["close"].rolling(window=self.fast_ma).mean()
            self.df["ma_slow"] = self.df["close"].rolling(window=self.slow_ma).mean()

        # 计算ATR (Average True Range)
        prev_close = self.df["close"].shift(1)
        tr1 = self.df["high"] - self.df["low"]
        tr2 = (self.df["high"] - prev_close).abs()
        tr3 = (self.df["low"] - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        self.df["atr"] = true_range.rolling(window=self.atr_period).mean()

    def _generate_signals(self):
        """生成交易信号：双均线金叉做多、死叉做空"""
        ma_fast = self.df["ma_fast"]
        ma_slow = self.df["ma_slow"]

        # 金叉：当前快线>慢线，且前一周期快线<=慢线
        long_cond = (ma_fast > ma_slow) & (ma_fast.shift(1) <= ma_slow.shift(1))
        # 死叉：当前快线<慢线，且前一周期快线>=慢线
        short_cond = (ma_fast < ma_slow) & (ma_fast.shift(1) >= ma_slow.shift(1))

        # 初始化信号为0（无仓位）
        self.df["signal"] = 0
        self.df.loc[long_cond, "signal"] = 1
        self.df.loc[short_cond, "signal"] = -1
