"""
QUANT-02: 组合回测服务 (Screen-to-Backtest)

等权组合回测：从选股结果构建等权投资组合，计算净值曲线与绩效指标。
支持买入持有 (buy_and_hold) 与定期再平衡 (weekly/monthly)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backend.services.performance import (
    annualized_return,
    max_drawdown,
    sharpe,
    volatility,
)

logger = logging.getLogger(__name__)


def _align_kline_frames(kline_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    将多只标的的 K 线 DataFrame 按日期对齐，返回收盘价宽表。

    Args:
        kline_dict: {symbol: DataFrame} 每个 DataFrame 需含 'close' 列和日期索引或 'date'/'time' 列

    Returns:
        pd.DataFrame: index=日期, columns=symbols, values=close prices
    """
    frames = {}
    for sym, df in kline_dict.items():
        if df is None or df.empty:
            continue
        df = df.copy()
        # 确定日期列
        date_col = None
        for c in ["date", "time", "datetime"]:
            if c in df.columns:
                date_col = c
                break
        if date_col is None:
            if isinstance(df.index, pd.DatetimeIndex):
                df = df[["close"]].copy()
                df.index.name = "date"
            else:
                continue
        else:
            df["date"] = pd.to_datetime(df[date_col])
            df = df.set_index("date")[["close"]]
        df.columns = [sym]
        frames[sym] = df

    if not frames:
        return pd.DataFrame()

    # 合并并按日期对齐 (inner join 只取共同交易日)
    result = pd.concat(frames.values(), axis=1, join="inner")
    result = result.dropna()
    return result


def _compute_rebalance_dates(dates: pd.DatetimeIndex, freq: str) -> set:
    """
    根据再平衡频率计算再平衡日期。

    Args:
        dates: 交易日序列
        freq: "buy_and_hold" | "weekly" | "monthly"

    Returns:
        需要再平衡的日期集合
    """
    if freq == "buy_and_hold":
        return {dates[0]} if len(dates) > 0 else set()

    rebalance = set()
    if freq == "weekly":
        prev_week = None
        for d in dates:
            week_key = d.isocalendar()[1]
            if week_key != prev_week:
                rebalance.add(d)
                prev_week = week_key
    elif freq == "monthly":
        prev_month = None
        for d in dates:
            month_key = (d.year, d.month)
            if month_key != prev_month:
                rebalance.add(d)
                prev_month = month_key
    else:
        # 默认买入持有
        rebalance.add(dates[0])
    return rebalance


def run_portfolio_backtest(
    symbols: List[str],
    kline_dict: Dict[str, pd.DataFrame],
    initial_capital: float = 100000.0,
    rebalance_freq: str = "monthly",
    commission_pct: float = 0.001,
) -> Dict[str, Any]:
    """
    等权组合回测。

    Args:
        symbols: 标的列表
        kline_dict: {symbol: K线 DataFrame}
        initial_capital: 初始资金
        rebalance_freq: "buy_and_hold" | "weekly" | "monthly"
        commission_pct: 单边手续费 (默认 0.1%)

    Returns:
        Tear Sheet 数据结构
    """
    if not symbols or not kline_dict:
        return _empty_result()

    # 1. 对齐收盘价宽表
    price_table = _align_kline_frames(kline_dict)
    if price_table.empty or len(price_table) < 2:
        return _empty_result()

    actual_symbols = list(price_table.columns)
    n = len(actual_symbols)

    # 2. 计算日收益率矩阵
    returns_table = price_table.pct_change().fillna(0)

    # 3. 确定再平衡日期
    rebalance_dates = _compute_rebalance_dates(price_table.index, rebalance_freq)

    # 4. 模拟组合净值
    # 等权: 每天各标的权重相等 (再平衡日重新分配)
    weights = pd.DataFrame(
        np.ones((len(price_table), n)) / n,
        index=price_table.index,
        columns=actual_symbols,
    )

    # 组合日收益 = sum(weight_i * return_i)
    portfolio_returns = (weights * returns_table).sum(axis=1)

    # 扣除再平衡日的交易成本
    for d in rebalance_dates:
        if d in portfolio_returns.index:
            # 再平衡成本 = 换手 * 手续费 (简化: 等权再平衡换手 = 2/N)
            turnover = 2.0 / n if n > 1 else 0
            portfolio_returns.loc[d] -= turnover * commission_pct

    # 净值曲线
    equity_curve = initial_capital * (1 + portfolio_returns).cumprod()

    # 5. 计算绩效指标
    daily_returns = portfolio_returns
    nav_series = equity_curve

    total_ret = (nav_series.iloc[-1] / initial_capital) - 1.0
    ann_ret = annualized_return(nav_series)
    sharpe_ratio = sharpe(daily_returns)
    max_dd = max_drawdown(nav_series)
    vol = volatility(daily_returns)
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0

    # 胜率: 日收益为正的比率
    positive_days = (daily_returns > 0).sum()
    total_days = (daily_returns != 0).sum()
    wr = positive_days / total_days if total_days > 0 else 0.0

    # 6. 各标的独立表现
    per_symbol = []
    for sym in actual_symbols:
        sym_returns = returns_table[sym]
        sym_nav = initial_capital / n * (1 + sym_returns).cumprod()
        per_symbol.append(
            {
                "symbol": sym,
                "total_return": round(float((sym_nav.iloc[-1] / (initial_capital / n) - 1) * 100), 2),
                "max_dd": round(float(max_drawdown(sym_nav) * 100), 2),
                "sharpe": round(float(sharpe(sym_returns)), 2),
            }
        )
    per_symbol.sort(key=lambda x: x["total_return"], reverse=True)

    # 7. 月度收益热力图
    monthly_returns = _compute_monthly_returns(daily_returns)

    # 8. 最长回撤期
    longest_dd = _compute_longest_drawdown(nav_series)

    # 9. 净值曲线数据
    equity_data = []
    cummax = nav_series.cummax()
    for dt, eq in nav_series.items():
        dd = (eq - cummax.loc[dt]) / cummax.loc[dt] if cummax.loc[dt] > 0 else 0
        equity_data.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "equity": round(float(eq), 2),
                "drawdown": round(float(dd * 100), 2),
            }
        )

    return {
        "metrics": {
            "total_return": f"{total_ret * 100:.2f}%",
            "annualized_return": f"{ann_ret * 100:.2f}%",
            "sharpe_ratio": f"{sharpe_ratio:.2f}",
            "max_drawdown": f"{max_dd * 100:.2f}%",
            "volatility": f"{vol * 100:.2f}%",
            "win_rate": f"{wr * 100:.1f}%",
            "calmar_ratio": f"{calmar:.2f}",
            "total_symbols": n,
            "rebalance_freq": rebalance_freq,
        },
        "equity_curve": equity_data,
        "per_symbol": per_symbol,
        "monthly_returns": monthly_returns,
        "longest_drawdown": longest_dd,
    }


def _compute_monthly_returns(daily_returns: pd.Series) -> List[List[float]]:
    """计算月度收益热力图数据 [year, month, return_pct]"""
    if daily_returns.empty:
        return []
    monthly = (1 + daily_returns).resample("ME").prod() - 1
    result = []
    for dt, ret in monthly.items():
        result.append([dt.year, dt.month - 1, round(float(ret * 100), 2)])
    return result


def _compute_longest_drawdown(nav: pd.Series) -> Dict[str, Any]:
    """计算最长回撤期"""
    if nav.empty or len(nav) < 2:
        return {"start": None, "end": None, "depth": 0, "duration_days": 0}

    cummax = nav.cummax()
    in_dd = False
    start = None
    longest_start = None
    longest_end = None
    longest_depth = 0.0
    current_depth = 0.0

    for i, (dt, eq) in enumerate(nav.items()):
        peak = cummax.iloc[i]
        if eq < peak:
            if not in_dd:
                in_dd = True
                start = dt
                current_depth = 0
            dd = (eq - peak) / peak if peak > 0 else 0
            if dd < current_depth:
                current_depth = dd
        else:
            if in_dd:
                duration = (dt - start).days if start else 0
                if duration > (longest_end - longest_start).days if longest_start and longest_end else 0:
                    longest_start = start
                    longest_end = dt
                    longest_depth = current_depth
                in_dd = False

    if longest_start is None:
        return {"start": None, "end": None, "depth": 0, "duration_days": 0}

    return {
        "start": longest_start.strftime("%Y-%m-%d"),
        "end": longest_end.strftime("%Y-%m-%d"),
        "depth": round(float(longest_depth * 100), 2),
        "duration_days": (longest_end - longest_start).days,
    }


def _empty_result() -> Dict[str, Any]:
    """空结果结构"""
    return {
        "metrics": {
            "total_return": "0.00%",
            "annualized_return": "0.00%",
            "sharpe_ratio": "0.00",
            "max_drawdown": "0.00%",
            "volatility": "0.00%",
            "win_rate": "0.0%",
            "calmar_ratio": "0.00",
            "total_symbols": 0,
            "rebalance_freq": "monthly",
        },
        "equity_curve": [],
        "per_symbol": [],
        "monthly_returns": [],
        "longest_drawdown": {"start": None, "end": None, "depth": 0, "duration_days": 0},
    }
