"""
PT-02a: 共享绩效指标库
======================
纯函数、矢量化（NumPy/Pandas）、无 I/O。
供纸面组合对比、回测报告、风控模块复用。
"""
from typing import List

import numpy as np
import pandas as pd


def sharpe(returns: pd.Series, freq: int = 252) -> float:
    """
    年化 Sharpe 比率（无风险利率 = 0）

    Args:
        returns: 日收益率序列
        freq: 年化因子（日线默认 252）

    Returns:
        年化 Sharpe，returns 为空或标准差为 0 时返回 0.0
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    std = returns.std()
    if std == 0 or np.isnan(std):
        return 0.0
    return float(returns.mean() / std * np.sqrt(freq))


def max_drawdown(nav: pd.Series) -> float:
    """
    最大回撤（返回负值，如 -0.15 表示 15% 回撤）

    Args:
        nav: 净值序列

    Returns:
        最大回撤（负值），nav 为空时返回 0.0
    """
    if nav.empty or len(nav) < 2:
        return 0.0
    cummax = nav.cummax()
    drawdown = (nav - cummax) / cummax
    return float(drawdown.min())


def annualized_return(nav: pd.Series, freq: int = 252) -> float:
    """
    年化收益率

    Args:
        nav: 净值序列
        freq: 年化因子

    Returns:
        年化收益率，nav 为空或首值为 0 时返回 0.0
    """
    if nav.empty or len(nav) < 2:
        return 0.0
    total_return = nav.iloc[-1] / nav.iloc[0]
    if total_return <= 0:
        return 0.0
    n_periods = len(nav) - 1
    if n_periods <= 0:
        return 0.0
    return float(total_return ** (freq / n_periods) - 1.0)


def volatility(returns: pd.Series, freq: int = 252) -> float:
    """
    年化波动率

    Args:
        returns: 日收益率序列
        freq: 年化因子

    Returns:
        年化波动率
    """
    if returns.empty or len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(freq))


def win_rate(trades: List[float]) -> float:
    """
    胜率

    Args:
        trades: 每笔交易盈亏列表（正=盈利，负=亏损）

    Returns:
        胜率（0~1），无交易时返回 0.0
    """
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t > 0)
    return wins / len(trades)


def tracking_error(r_a: pd.Series, r_b: pd.Series, freq: int = 252) -> float:
    """
    年化跟踪误差（Tracking Error）

    Args:
        r_a: 策略 A 日收益率序列
        r_b: 策略 B（基准）日收益率序列
        freq: 年化因子

    Returns:
        年化跟踪误差。序列长度不一致时按较短的对齐。
    """
    if r_a.empty or r_b.empty:
        return 0.0
    # 对齐长度
    min_len = min(len(r_a), len(r_b))
    diff = r_a.iloc[:min_len].values - r_b.iloc[:min_len].values
    diff_series = pd.Series(diff)
    if diff_series.empty or len(diff_series) < 2:
        return 0.0
    return float(diff_series.std() * np.sqrt(freq))


def active_return(r_a: pd.Series, r_b: pd.Series) -> pd.Series:
    """
    超额收益序列（逐期差）

    Args:
        r_a: 策略 A 日收益率序列
        r_b: 策略 B（基准）日收益率序列

    Returns:
        超额收益序列
    """
    min_len = min(len(r_a), len(r_b))
    return r_a.iloc[:min_len] - r_b.iloc[:min_len]


def cumulative_return(nav: pd.Series) -> pd.Series:
    """
    累计收益率序列（归一化为从 0 开始）

    Args:
        nav: 净值序列

    Returns:
        累计收益率序列
    """
    if nav.empty or nav.iloc[0] == 0:
        return pd.Series(dtype=float)
    return nav / nav.iloc[0] - 1.0


def signal_consistency(positions_a: List[str], positions_b: List[str]) -> float:
    """
    信号一致率：两个持仓集合的 Jaccard 相似度

    Args:
        positions_a: 策略 A 持仓标的列表
        positions_b: 策略 B 持仓标的列表

    Returns:
        一致率（0~1），两个都为空时返回 1.0
    """
    set_a = set(positions_a)
    set_b = set(positions_b)
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 1.0
    intersection = set_a & set_b
    return len(intersection) / len(union)
