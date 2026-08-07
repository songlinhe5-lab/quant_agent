"""YFinance 工具函数（复制自 backend.services.yfinance.utils，物理解耦）

去除对 backend.core.middleware 的 Prometheus 出向指标依赖（子服务不上报主集群）。
"""

from datetime import datetime, timedelta
from typing import List, Optional


def format_yf_ticker(ticker: str) -> str:
    """标准化雅虎财经代码（与全局 format_ticker 一致）。"""
    if not ticker:
        return ticker
    t = ticker.strip().upper()

    # 1. Futu 前缀格式转雅虎后缀
    if t.startswith("US."):
        return t[3:]
    if t.startswith("HK."):
        return f"{t[3:]}.HK"
    if t.startswith("SH."):
        return f"{t[3:]}.SS"
    if t.startswith("SZ."):
        return f"{t[3:]}.SZ"

    # 2. 已是雅虎后缀格式，直接返回
    if t.endswith((".HK", ".SS", ".SZ", ".T")):
        return t

    # 3. 纯数字美股 ADR → 原样
    return t


def resolve_date_range(
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    default_period: str = "1mo",
    range_days: int = 366,
) -> tuple:
    """解析雅虎财经日期范围参数，返回 (period, start, end)。"""
    if start and end:
        return None, start, end

    if period:
        return period, None, None

    # 默认回退到 N 天前
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=range_days)
    return None, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d")


def get_valid_earnings_dates(ticker: str, earnings_dates: List[dict]) -> List[dict]:
    """过滤掉未来的财报日期，只保留已公布的。"""
    today = datetime.now()
    valid = []
    for e in earnings_dates or []:
        try:
            ed = datetime.strptime(e.get("period", ""), "%Y-%m-%d")
            if ed <= today:
                valid.append(e)
        except Exception:
            continue
    return valid
