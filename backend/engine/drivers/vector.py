"""
BT-01c · VectorBT 快路径执行器

定位：不是第二种语义，而是同一策略的加速执行计划。
适用条件：strategy.signals(df, params) 返回非 None。

费率/滑点参数与 SimBroker 同源配置，保证结果可比。

设计文档：docs/15. 回测实盘同构引擎设计.md §四.2
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Type

import pandas as pd

from backend.engine.strategy import Strategy

logger = logging.getLogger(__name__)


@dataclass
class VectorConfig:
    """VectorBT 执行配置（与 SimBrokerConfig 对齐）"""

    initial_capital: float = 100000.0
    commission_pct: float = 0.0005
    slippage_pct: float = 0.001
    freq: str = "1D"


@dataclass
class VectorResult:
    """VectorBT 执行结果"""

    metrics: Dict[str, Any]
    equity_curve: list
    trades: list
    signals: pd.Series  # 原始信号列


class VectorExecutor:
    """VectorBT 快路径执行器

    消费策略的 signals() 类方法，直接生成信号 → VectorBT Portfolio。
    """

    def __init__(self, config: VectorConfig) -> None:
        self.config = config

    def run(
        self,
        strategy_cls: Type[Strategy],
        params: Dict[str, Any],
        df: pd.DataFrame,
    ) -> VectorResult:
        """运行 VectorBT 快路径

        Args:
            strategy_cls: 策略类（必须实现 signals() 方法）
            params: 策略参数
            df: 完整 OHLCV DataFrame

        Returns:
            VectorResult

        Raises:
            ValueError: 策略不支持矢量化
        """
        # 检查策略是否支持矢量化
        if not strategy_cls.is_vectorizable():
            raise ValueError(f"Strategy {strategy_cls.__name__} does not support vectorized execution")

        # 生成信号
        signals = strategy_cls.signals(df, params)
        if signals is None:
            raise ValueError("signals() returned None")

        # 准备数据
        df = self._prepare_dataframe(df)

        # 对齐信号与数据
        signals = signals.reindex(df.index).fillna(0).astype(int)

        # 构建 VectorBT 输入
        entries = signals == 1
        exits = signals == 0
        short_entries = signals == -1
        short_exits = signals == 0

        try:
            import vectorbt as vbt

            pf = vbt.Portfolio.from_signals(
                close=df["close"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                entries=entries,
                exits=exits,
                short_entries=short_entries,
                short_exits=short_exits,
                init_cash=self.config.initial_capital,
                fees=self.config.commission_pct,
                slippage=self.config.slippage_pct,
                upon_long_conflict="ignore",
                upon_short_conflict="ignore",
                freq=self.config.freq,
            )

            # 提取指标
            stats = pf.stats()
            metrics = self._extract_metrics(stats, pf)

            # 提取权益曲线
            equity_curve = self._extract_equity_curve(pf, df)

            # 提取交易列表
            trades = self._extract_trades(pf)

            return VectorResult(
                metrics=metrics,
                equity_curve=equity_curve,
                trades=trades,
                signals=signals,
            )

        except ImportError:
            logger.warning("vectorbt not installed, falling back to simple calculation")
            return self._fallback_execution(df, signals)

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备 DataFrame"""
        df = df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.loc[:, ~df.columns.duplicated()].copy()
        # 统一列名为小写
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col.lower()] = df[col]
        return df.dropna()

    def _extract_metrics(self, stats, pf) -> Dict[str, Any]:
        """提取指标"""
        from backend.backtest.sandbox import _safe_stat

        total_return = _safe_stat(stats, "Total Return [%]") / 100.0
        sharpe = _safe_stat(stats, "Sharpe Ratio")
        max_dd = _safe_stat(stats, "Max Drawdown [%]") / 100.0
        win_rate = _safe_stat(stats, "Win Rate [%]") / 100.0
        total_fees = _safe_stat(stats, "Total Fees Paid")

        return {
            "engine": "⚡ VectorBT",
            "total_return": f"{total_return * 100:.2f}%",
            "sharpe_ratio": f"{sharpe:.2f}",
            "max_drawdown": f"{max_dd * 100:.2f}%",
            "win_rate": f"{win_rate * 100:.2f}%",
            "total_friction_cost": f"${total_fees:,.2f}",
        }

    def _extract_equity_curve(self, pf, df) -> list:
        """提取权益曲线"""
        equity_s = pf.value()
        benchmark_start = df["close"].iloc[0]
        initial = self.config.initial_capital

        result = []
        for date, eq in equity_s.items():
            date_str = str(date).split(" ")[0].split("T")[0]
            price = df.loc[date, "close"] if date in df.index else 0
            result.append({
                "date": date_str,
                "equity": round(eq, 2),
                "benchmark": round(initial * (price / benchmark_start), 2),
            })
        return result

    def _extract_trades(self, pf) -> list:
        """提取交易列表"""
        trades = []
        if pf.trades.records_readable.empty:
            return trades

        for _, tr in pf.trades.records_readable.iterrows():
            entry_date = str(tr["Entry Timestamp"]).split(" ")[0].split("T")[0]
            entry_action = "BUY" if tr["Direction"] == "Long" else "SHORT"
            trades.append({
                "date": entry_date,
                "action": entry_action,
                "price": round(tr.get("Avg Entry Price", tr.get("Entry Price", 0)), 4),
                "shares": abs(int(tr["Size"])),
            })

            exit_date = str(tr["Exit Timestamp"]).split(" ")[0].split("T")[0]
            exit_action = "SELL" if tr["Direction"] == "Long" else "COVER"
            trades.append({
                "date": exit_date,
                "action": exit_action,
                "price": round(tr.get("Avg Exit Price", tr.get("Exit Price", 0)), 4),
                "shares": abs(int(tr["Size"])),
                "profit": round(tr["PnL"], 4),
            })

        trades.sort(key=lambda x: x["date"])
        return trades

    def _fallback_execution(self, df: pd.DataFrame, signals: pd.Series) -> VectorResult:
        """简单回退执行（无 VectorBT 时）"""
        df = self._prepare_dataframe(df)
        signals = signals.reindex(df.index).fillna(0).astype(int)

        # 简单模拟
        cash = self.config.initial_capital
        position = 0
        equity_curve = []
        trades = []

        for i, (date, row) in enumerate(df.iterrows()):
            price = row["close"]
            signal = signals.iloc[i] if i < len(signals) else 0

            if signal == 1 and position == 0:
                # 买入
                exec_price = price * (1 + self.config.slippage_pct)
                shares = int(cash / exec_price)
                if shares > 0:
                    cost = shares * exec_price * (1 + self.config.commission_pct)
                    cash -= cost
                    position = shares
                    trades.append({
                        "date": str(date).split("T")[0],
                        "action": "BUY",
                        "price": round(exec_price, 4),
                        "shares": shares,
                    })

            elif signal == -1 and position > 0:
                # 卖出
                exec_price = price * (1 - self.config.slippage_pct)
                revenue = position * exec_price * (1 - self.config.commission_pct)
                cash += revenue
                trades.append({
                    "date": str(date).split("T")[0],
                    "action": "SELL",
                    "price": round(exec_price, 4),
                    "shares": position,
                })
                position = 0

            equity = cash + position * price
            equity_curve.append({
                "date": str(date).split("T")[0],
                "equity": round(equity, 2),
            })

        final_equity = equity_curve[-1]["equity"] if equity_curve else self.config.initial_capital
        total_return = (final_equity - self.config.initial_capital) / self.config.initial_capital

        return VectorResult(
            metrics={
                "engine": "⚡ Fallback",
                "total_return": f"{total_return * 100:.2f}%",
                "sharpe_ratio": "N/A",
                "max_drawdown": "N/A",
                "win_rate": "N/A",
                "total_friction_cost": "$0.00",
            },
            equity_curve=equity_curve,
            trades=trades,
            signals=signals,
        )
