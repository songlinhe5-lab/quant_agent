"""
内置矢量化策略：RSI/MACD 动能背离 + KDJ 交叉共振
"""

from typing import Any, Dict

import pandas as pd
import vectorbt as vbt

from .sandbox import _safe_stat


class DivergenceResonanceStrategy:
    """
    [高频回测引擎]
    RSI/MACD 动能背离 + KDJ 交叉共振策略
    基于完全矢量化运算 (Vectorized) 实现百万级 K 线的极速回测
    """

    def __init__(
        self,
        df: pd.DataFrame,
        initial_capital: float = 100000.0,
        atr_multiplier: float = 2.0,
        commission_pct: float = 0.0005,
        slippage_pct: float = 0.001,
    ):
        self.df = df.copy()
        if isinstance(self.df.columns, pd.MultiIndex):
            self.df.columns = self.df.columns.get_level_values(0)
        self.df = self.df.loc[:, ~self.df.columns.duplicated()].copy()

        self.initial_capital = initial_capital
        self.atr_multiplier = atr_multiplier
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct

    def _calculate_indicators(self):
        df = self.df

        # 1. MACD
        exp1 = df["Close"].ewm(span=12, adjust=False).mean()
        exp2 = df["Close"].ewm(span=26, adjust=False).mean()
        df["macd_diff"] = exp1 - exp2
        df["macd_dea"] = df["macd_diff"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = (df["macd_diff"] - df["macd_dea"]) * 2

        # 2. RSI (14)
        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # 3. KDJ (9, 3, 3)
        low_min = df["Low"].rolling(window=9, min_periods=1).min()
        high_max = df["High"].rolling(window=9, min_periods=1).max()
        rsv = (df["Close"] - low_min) / (high_max - low_min + 1e-9) * 100
        df["k"] = rsv.fillna(50).ewm(com=2, adjust=False).mean()
        df["d"] = df["k"].ewm(com=2, adjust=False).mean()
        df["j"] = 3 * df["k"] - 2 * df["d"]

        # 4. ATR (14) - 用于波动率动态止损
        prev_close = df["Close"].shift(1)
        tr1 = df["High"] - df["Low"]
        tr2 = (df["High"] - prev_close).abs()
        tr3 = (df["Low"] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    def _generate_signals(self):
        df = self.df

        df["prev_close"] = df["Close"].shift(1)
        df["min_5"] = df["Close"].rolling(5).min().shift(1)
        df["max_5"] = df["Close"].rolling(5).max().shift(1)

        df["prev_rsi"] = df["rsi"].shift(1)
        df["prev_hist"] = df["macd_hist"].shift(1)
        df["prev_k"] = df["k"].shift(1)
        df["prev_d"] = df["d"].shift(1)

        df["vol_ma5"] = df["Volume"].rolling(5).mean().shift(1)

        # ==========================================
        # 🚀 核心算法：矩阵运算级形态识别
        # ==========================================
        is_new_low = (df["Close"] < df["prev_close"]) & (df["Close"] <= df["min_5"])
        is_new_high = (df["Close"] > df["prev_close"]) & (df["Close"] >= df["max_5"])

        is_vol_confirmed = (df["Volume"] < df["vol_ma5"] * 0.8) | (df["Volume"] > df["vol_ma5"] * 1.2)

        rsi_bottom = is_new_low & (df["rsi"] > df["prev_rsi"]) & (df["rsi"] < 40) & is_vol_confirmed
        macd_bottom = is_new_low & (df["macd_hist"] < 0) & (df["macd_hist"] > df["prev_hist"]) & is_vol_confirmed
        kdj_golden = (df["k"] > df["d"]) & (df["prev_k"] <= df["prev_d"]) & (df["k"] < 50)

        rsi_top = is_new_high & (df["rsi"] < df["prev_rsi"]) & (df["rsi"] > 60) & is_vol_confirmed
        macd_top = is_new_high & (df["macd_hist"] > 0) & (df["macd_hist"] < df["prev_hist"]) & is_vol_confirmed
        kdj_death = (df["k"] < df["d"]) & (df["prev_k"] >= df["prev_d"]) & (df["k"] > 50)

        df["signal"] = 0
        buy_mask = (rsi_bottom | macd_bottom) & kdj_golden
        sell_mask = (rsi_top | macd_top) & kdj_death

        df.loc[buy_mask, "signal"] = 1
        df.loc[sell_mask, "signal"] = -1

    def run(self) -> Dict[str, Any]:
        self._calculate_indicators()
        self._generate_signals()
        df = self.df.dropna().copy()

        entries = df["signal"] == 1
        exits = df["signal"] == 0
        short_entries = df["signal"] == -1
        short_exits = df["signal"] == 0

        sl_trail_pct = (df["atr"] * self.atr_multiplier) / df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=df["Close"],
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=short_exits,
            init_cash=float(self.initial_capital),
            fees=self.commission_pct,
            slippage=self.slippage_pct,
            sl_trail=sl_trail_pct,
            upon_long_conflict="ignore",
            upon_short_conflict="ignore",
            freq="1D",
        )

        stats = pf.stats()
        total_return = _safe_stat(stats, "Total Return [%]") / 100.0
        ann_return = _safe_stat(stats, "Ann. Return [%]") / 100.0
        sharpe = _safe_stat(stats, "Sharpe Ratio")
        max_dd = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        total_trades = int(_safe_stat(stats, "Total Trades"))
        profit_factor = _safe_stat(stats, "Profit Factor")
        total_friction_cost = _safe_stat(stats, "Total Fees Paid")

        trades_list = []
        if not pf.trades.records_readable.empty:
            for _, tr in pf.trades.records_readable.iterrows():
                entry_date_str = str(tr["Entry Timestamp"]).split(" ")[0].split("T")[0]
                entry_action = "BUY" if tr["Direction"] == "Long" else "SHORT"
                trades_list.append(
                    {
                        "date": entry_date_str,
                        "action": entry_action,
                        "price": round(tr.get("Avg Entry Price") or tr.get("Entry Price", 0), 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": 0.0,
                    }
                )

                exit_date_str = str(tr["Exit Timestamp"]).split(" ")[0].split("T")[0]
                exit_action = "SELL" if tr["Direction"] == "Long" else "COVER"
                trades_list.append(
                    {
                        "date": exit_date_str,
                        "action": exit_action,
                        "price": round(tr.get("Avg Exit Price") or tr.get("Exit Price", 0), 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": round(tr["PnL"], 2),
                    }
                )
            trades_list.sort(key=lambda x: x["date"])

        df_chart = df.copy()
        df_chart["date"] = df_chart.index.astype(str).str.split(" ").str[0].str.split("T").str[0]
        df_chart["price"] = df_chart["Close"]
        df_chart["equity"] = pf.value().values
        df_chart["benchmark"] = self.initial_capital * (df_chart["Close"] / df_chart["Close"].iloc[0])
        equity_curve = (
            df_chart[["date", "equity", "benchmark", "price"]]
            .iloc[:: max(1, len(df_chart) // 200)]
            .to_dict(orient="records")
        )

        return {
            "metrics": {
                "total_return": f"{total_return * 100:.2f}%",
                "annualized_return": f"{ann_return * 100:.2f}%",
                "sharpe_ratio": f"{sharpe:.2f}",
                "max_drawdown": f"{max_dd * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_trades": total_trades,
                "profit_factor": f"{profit_factor:.2f}",
                "total_friction_cost": f"${total_friction_cost:,.2f}",
            },
            "equity_curve": equity_curve,
            "trades": trades_list,
            "limit_orders": [],
        }
