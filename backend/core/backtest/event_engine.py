"""
事件驱动回测引擎 + 动态沙箱回测入口
"""

import collections
import datetime
import itertools
import math
import random
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd
import vectorbt as vbt

from .sandbox import BaseStrategySandbox, SandboxTimeoutTracer
from .sandbox import SAFE_BUILTINS, _safe_stat, _verify_safe_code


class EventDrivenBacktestEngine:
    """
    高保真事件驱动回测引擎 (Event-Driven Backtester)
    支持逐根 K 线推进、限价单穿透、动态止损以及真实的滑点与手续费磨损计算
    """

    def __init__(
        self,
        strategy_instance,
        df: pd.DataFrame,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0005,
        slippage_pct: float = 0.001,
        debug_mode: bool = False,
    ):
        self.strategy = strategy_instance
        self.df = df.copy()
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.debug_mode = debug_mode
        self.cash = initial_capital
        self.position = 0
        self.equity_curve = []
        self.trades = []
        self.total_friction_cost = 0.0
        self.pending_orders = []  # 💡 新增：挂单簿
        self.debug_logs = []  # 💡 新增：逐 K 线调试日志

    def _execute_buy(self, base_price: float, date_str: str, stop_loss: Optional[float] = None):
        """内部撮合：买入执行"""
        exec_price = base_price * (1 + self.slippage_pct)
        turnover = self.cash * 0.95
        fee = turnover * self.commission_pct
        trade_value = turnover - fee
        shares = int(trade_value / exec_price)

        if shares > 0:
            real_turnover = shares * exec_price
            real_fee = real_turnover * self.commission_pct
            self.cash -= real_turnover + real_fee
            self.position = shares
            self.total_friction_cost += real_fee + (shares * base_price * self.slippage_pct)

            if hasattr(self.strategy, "_position_size"):
                self.strategy._position_size = shares
                self.strategy._position_data = {
                    "size": shares,
                    "entry_price": exec_price,
                    "stop_loss": stop_loss,
                }

            self.trades.append(
                {
                    "date": date_str,
                    "action": "BUY",
                    "price": round(exec_price, 2),
                    "shares": shares,
                    "profit": 0.0,
                }
            )

    def _execute_sell(self, base_price: float, date_str: str):
        """内部撮合：卖出平仓执行"""
        exec_price = base_price * (1 - self.slippage_pct)
        revenue = self.position * exec_price
        fee = revenue * self.commission_pct

        buy_trades = [t for t in self.trades if t["action"] == "BUY"]
        last_buy_price = buy_trades[-1]["price"] if buy_trades else exec_price
        profit = revenue - fee - (self.position * last_buy_price)
        self.cash += revenue - fee

        self.total_friction_cost += fee + (self.position * base_price * self.slippage_pct)

        self.trades.append(
            {
                "date": date_str,
                "action": "SELL",
                "price": round(exec_price, 2),
                "shares": self.position,
                "profit": round(profit, 2),
            }
        )

        self.position = 0
        if hasattr(self.strategy, "_position_size"):
            self.strategy._position_size = 0
            self.strategy._position_data = {}

    def run(self) -> dict:
        df = self.df.dropna().copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()].copy()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col.lower()] = df[col]

        if len(df) < 10:
            raise ValueError("回测数据长度不足 (至少需要 10 根 K 线)")

        benchmark_start_price = float(df.iloc[0]["close"])

        for i in range(10, len(df)):
            window_df = df.iloc[: i + 1]
            current_bar = window_df.iloc[-1]
            current_price = float(current_bar["close"])
            current_open = float(current_bar.get("open", current_price))
            current_high = float(current_bar.get("high", current_price))
            current_low = float(current_bar.get("low", current_price))
            date_str = str(current_bar.name).split(" ")[0].split("T")[0]

            # --- 1. 检查并撮合历史挂单 (Limit Orders) ---
            for order in list(self.pending_orders):
                if order["action"] == "buy" and self.position == 0:
                    if current_low <= order["limit_price"]:
                        base_price = min(order["limit_price"], current_open)
                        self._execute_buy(base_price, date_str, order.get("stop_loss"))
                        self.pending_orders.remove(order)

                elif order["action"] == "sell" and self.position > 0:
                    if current_high >= order["limit_price"]:
                        base_price = max(order["limit_price"], current_open)
                        self._execute_sell(base_price, date_str)
                        self.pending_orders.remove(order)

            # --- 2. 动态止损与风控拦截 ---
            if hasattr(self.strategy, "_position_data") and self.position > 0:
                sl = self.strategy._position_data.get("stop_loss")
                if sl and current_low <= sl:
                    base_price = min(sl, current_open)
                    self._execute_sell(base_price, date_str)
                    self.pending_orders = [o for o in self.pending_orders if o["action"] != "sell"]

            # --- 3. 策略产生新信号 ---
            signal = None
            if hasattr(self.strategy, "on_bar"):
                signal = self.strategy.on_bar(window_df)
            elif hasattr(self.strategy, "on_tick"):
                signal = self.strategy.on_tick(window_df)

            # --- 4. 信号与订单分发 ---
            if signal and isinstance(signal, dict):
                action = str(signal.get("action", "")).lower()
                limit_price = signal.get("limit_price")

                if action == "cancel":
                    self.pending_orders.clear()

                elif action == "buy" and self.position == 0:
                    if limit_price:
                        self.pending_orders.append(
                            {
                                "action": "buy",
                                "limit_price": float(limit_price),
                                "stop_loss": signal.get("stop_loss"),
                            }
                        )
                    else:
                        self._execute_buy(current_price, date_str, signal.get("stop_loss"))

                elif action in ["sell", "close"] and self.position > 0:
                    if limit_price:
                        self.pending_orders.append({"action": "sell", "limit_price": float(limit_price)})
                    else:
                        self._execute_sell(current_price, date_str)
                        self.pending_orders.clear()

            # --- 5. 记录 Debug 日志 ---
            current_equity = self.cash + self.position * current_price
            if self.debug_mode:
                sig_str = str(signal) if signal else "Hold"
                log_line = f"[{date_str}] P:{current_price:.2f} | Pos:{self.position} | Cash:{self.cash:.2f} | Eq:{current_equity:.2f} | Sig:{sig_str} | Pending:{len(self.pending_orders)}"  # noqa: E501
                self.debug_logs.append(log_line)

            self.equity_curve.append(
                {
                    "date": date_str,
                    "equity": round(current_equity, 2),
                    "benchmark": round(
                        self.initial_capital * (current_price / benchmark_start_price),
                        2,
                    ),
                    "price": round(current_price, 2),
                }
            )

        current_equity = self.cash + self.position * current_price
        total_return_val = (current_equity - self.initial_capital) / self.initial_capital

        if len(self.equity_curve) > 0:
            equity_series = pd.Series([e["equity"] for e in self.equity_curve])
            daily_returns = equity_series.pct_change().dropna()
            sharpe_ratio = (
                (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
                if len(daily_returns) > 0 and daily_returns.std() != 0
                else 0.0
            )
            cummax = equity_series.cummax()
            drawdowns = (equity_series - cummax) / cummax
            max_drawdown = drawdowns.min() if len(drawdowns) > 0 else 0.0
        else:
            sharpe_ratio = 0.0
            max_drawdown = 0.0

        sell_trades = [t for t in self.trades if t["action"] == "SELL"]
        winning_trades = [t for t in sell_trades if t["profit"] > 0]
        win_rate = len(winning_trades) / len(sell_trades) if len(sell_trades) > 0 else 0.0

        return {
            "metrics": {
                "engine": "🐢 Event-Driven",
                "total_return": f"{total_return_val * 100:.2f}%",
                "sharpe_ratio": f"{sharpe_ratio:.2f}",
                "max_drawdown": f"{max_drawdown * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_friction_cost": f"${self.total_friction_cost:,.2f}",
            },
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "debug_logs": self.debug_logs,
        }


def run_dynamic_sandbox_backtest(
    source_code: str,
    class_name: str,
    params: dict,
    df: pd.DataFrame,
    initial_capital: float = 100000.0,
    debug_mode: bool = False,
) -> dict:
    """
    运行大模型生成的动态策略 (真实逐 K 线事件驱动沙箱)
    """
    _verify_safe_code(source_code)

    local_scope = {}
    global_scope = {
        "__builtins__": SAFE_BUILTINS,
        "np": np,
        "pd": pd,
        "Dict": Dict,
        "Optional": Optional,
        "List": List,
        "Any": Any,
        "Literal": Literal,
        "Tuple": Tuple,
        "Union": Union,
        "Set": Set,
        "Callable": Callable,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "collections": collections,
        "datetime": datetime,
        "math": math,
        "random": random,
        "itertools": itertools,
        "DataFrame": pd.DataFrame,
        "Series": pd.Series,
        "BaseStrategy": BaseStrategySandbox,
    }

    with SandboxTimeoutTracer(timeout_seconds=5.0):
        exec(source_code, global_scope, local_scope)
        StrategyClass = local_scope.get(class_name)
        if not StrategyClass:
            raise ValueError(f"未在代码中找到名为 {class_name} 的策略类")

        strategy_instance = StrategyClass(**params)

    # 💡 如果开启了 debug_mode，主动降级回高保真事件驱动引擎以捕获逐 K 线内部状态
    if (
        not debug_mode
        and hasattr(strategy_instance, "_calculate_indicators")
        and hasattr(strategy_instance, "_generate_signals")
    ):
        print(
            f"⚡️ [Backtest Engine] 检测到 {class_name} 支持矢量化，启用 Numba 高频引擎进行回测！"  # noqa: E501
        )

        df_copy = df.copy()
        if isinstance(df_copy.columns, pd.MultiIndex):
            df_copy.columns = df_copy.columns.get_level_values(0)
        df_copy = df_copy.loc[:, ~df_copy.columns.duplicated()].copy()

        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df_copy.columns:
                df_copy[col.lower()] = df_copy[col]

        strategy_instance.df = df_copy
        with SandboxTimeoutTracer(timeout_seconds=5.0):
            strategy_instance._calculate_indicators()
            strategy_instance._generate_signals()

        res_df = strategy_instance.df
        if "signal" not in res_df.columns:
            res_df["signal"] = 0
        if "atr" not in res_df.columns:
            res_df["atr"] = res_df["Close"].diff().abs().rolling(14).mean().fillna(res_df["Close"] * 0.01)

        res_df = res_df.dropna().copy()

        if len(res_df) < 10:
            raise ValueError("回测数据长度不足 (清洗 NaN 后数据少于 10 根)")

        entries = res_df["signal"] == 1
        exits = res_df["signal"] == 0
        short_entries = res_df["signal"] == -1
        short_exits = res_df["signal"] == 0

        atr_multi = params.get(
            "atr_multiplier",
            params.get("stop_loss_atr_multiple", params.get("sl_multiplier", 2.0)),
        )
        sl_trail_pct = (res_df["atr"] * float(atr_multi)) / res_df["Close"]

        pf = vbt.Portfolio.from_signals(
            close=res_df["Close"],
            open=res_df["Open"],
            high=res_df["High"],
            low=res_df["Low"],
            entries=entries,
            exits=exits,
            short_entries=short_entries,
            short_exits=short_exits,
            init_cash=float(initial_capital),
            fees=0.0005,
            slippage=0.001,
            sl_trail=sl_trail_pct,
            upon_long_conflict="ignore",
            upon_short_conflict="ignore",
            freq="1D",
        )

        stats = pf.stats()
        total_return_val = _safe_stat(stats, "Total Return [%]") / 100.0
        sharpe_ratio = _safe_stat(stats, "Sharpe Ratio")
        max_drawdown = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        total_fees = _safe_stat(stats, "Total Fees Paid")

        equity_curve = []
        trades = []

        equity_s = pf.value()
        benchmark_start_price = res_df["Close"].iloc[0]

        for date, eq in equity_s.items():
            date_str = str(date).split(" ")[0].split("T")[0]
            price = res_df.loc[date, "Close"]
            equity_curve.append(
                {
                    "date": date_str,
                    "equity": round(eq, 2),
                    "benchmark": round(initial_capital * (price / benchmark_start_price), 2),
                }
            )

        if not pf.trades.records_readable.empty:
            for _, tr in pf.trades.records_readable.iterrows():
                entry_date_str = str(tr["Entry Timestamp"]).split(" ")[0].split("T")[0]
                entry_action = "BUY" if tr["Direction"] == "Long" else "SHORT"
                trades.append(
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
                trades.append(
                    {
                        "date": exit_date_str,
                        "action": exit_action,
                        "price": round(tr.get("Avg Exit Price") or tr.get("Exit Price", 0), 2),
                        "shares": abs(int(tr["Size"])),
                        "profit": round(tr["PnL"], 2),
                    }
                )

            trades.sort(key=lambda x: x["date"])

        return {
            "metrics": {
                "engine": "⚡ VectorBT",
                "total_return": f"{total_return_val * 100:.2f}%",
                "sharpe_ratio": f"{sharpe_ratio:.2f}",
                "max_drawdown": f"{max_drawdown * 100:.2f}%",
                "win_rate": f"{win_rate * 100:.2f}%",
                "total_friction_cost": f"${total_fees:,.2f}",
            },
            "equity_curve": equity_curve,
            "trades": trades,
            "limit_orders": [],
        }

    # =========================================================================
    # 启用高保真事件驱动引擎兜底 (处理无法被 Numba 矢量化的复杂脚本)
    # =========================================================================
    if debug_mode:
        print(
            "🐛 [Backtest Engine] 调试模式已开启，强制降级至高保真事件驱动引擎以捕获逐 K 线状态！"  # noqa: E501
        )
    engine = EventDrivenBacktestEngine(strategy_instance, df, initial_capital=initial_capital, debug_mode=debug_mode)
    with SandboxTimeoutTracer(timeout_seconds=10.0):
        return engine.run()
