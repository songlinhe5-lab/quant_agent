import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from backend.core.backtest_engine import BaseStrategySandbox as BaseStrategy

# 配对交易策略 (Pairs Trading Strategy)
# QuantEdge Strategy Dev Workbench
import numpy as np
from typing import Dict, Optional, Literal

class PairsTradingBot:
    """Z-Score 均值回归配对交易策略"""

    def __init__(
        self,
        stock1: str = "00700.HK",
        stock2: str = "09988.HK",
        entry_z:  float = 2.5,
        exit_z:   float = 0.5,
        pos_size: float = 0.5,
        ma_type:  Literal['SMA', 'EMA', 'WMA'] = 'SMA',
    ):
        self.stock1    = stock1
        self.stock2    = stock2
        self.entry_z   = entry_z
        self.exit_z    = exit_z
        self.pos_size  = pos_size
        self.ma_type   = ma_type
        self.position: Optional[str] = None

    def calc_zscore(self, p1: np.ndarray, p2: np.ndarray) -> float:
        spread = p1 - p2
        return float((spread[-1] - spread.mean()) / spread.std())

    def on_tick(self, data: Dict) -> Optional[str]:
        z = self.calc_zscore(
            data[self.stock1]["price"],
            data[self.stock2]["price"],
        )

        if z > self.entry_z and not self.position:
            self.position = "short_spread"
            return f"SHORT {self.stock1} | LONG {self.stock2}"

        elif z < -self.entry_z and not self.position:
            self.position = "long_spread"
            return f"LONG {self.stock1} | SHORT {self.stock2}"

        elif abs(z) < self.exit_z and self.position:
            self.position = None
            return "CLOSE ALL"

        return None