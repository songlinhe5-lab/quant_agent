"""BaoStock 查询服务：历史 K 线（含估值列）/ 季频财务 / 复权因子 / 股票基础信息。

全部同步阻塞（worker 侧 to_thread）；SDK 延迟导入。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.baostock.client import _ensure_login, normalize_bs_code, safe_query
from data_subservice._internal.logger import logger

_KLINE_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,"
    "turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)

_FREQ_MAP = {"d": "d", "w": "w", "m": "m", "5": "5", "15": "15", "30": "30", "60": "60"}
_ADJUST_MAP = {"none": "3", "front": "2", "back": "1"}  # baostock: 1后复权 2前复权 3不复权

# 季频财务四张表（docs/28 §1.2 CN 数字层先行指标；全表 XBRL 走巨潮/东财，此处为稳定口径）
_FUNDAMENTAL_TABLES = (
    ("query_profit_data", "profit"),
    ("query_growth_data", "growth"),
    ("query_balance_data", "balance"),
    ("query_cashflow_data", "cashflow"),
)


def get_kline(
    symbol: str,
    *,
    start_date: str = "",
    end_date: str = "",
    frequency: str = "d",
    adjust: str = "front",
) -> dict[str, Any]:
    """日/周/月/分钟 K 线（自带 peTTM/pbMRQ 等估值列，1990 至今，T+1）。"""
    code = normalize_bs_code(symbol)
    freq = _FREQ_MAP.get(str(frequency).lower())
    if freq is None:
        raise ValueError(f"不支持的 K 线周期: {frequency}（d/w/m/5/15/30/60）")
    adjustflag = _ADJUST_MAP.get(str(adjust).lower())
    if adjustflag is None:
        raise ValueError(f"不支持的复权方式: {adjust}（front/back/none）")

    bs = _ensure_login()
    rows = safe_query(
        bs,
        "query_history_k_data_plus",
        code,
        _KLINE_FIELDS,
        start_date=start_date or "1990-01-01",
        end_date=end_date or "2100-01-01",
        frequency=freq,
        adjustflag=adjustflag,
    )
    return {"status": "success", "source": "baostock", "symbol": code, "frequency": freq, "data": rows}


def get_quarter_fundamental(symbol: str, year: int, quarter: int) -> dict[str, Any]:
    """季频财务四表合并（profit/growth/balance/cashflow），键前缀区分口径冲突。"""
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter 须为 1~4: {quarter}")
    code = normalize_bs_code(symbol)
    bs = _ensure_login()

    out: dict[str, Any] = {}
    for fn_name, prefix in _FUNDAMENTAL_TABLES:
        rows = safe_query(bs, fn_name, code, int(year), int(quarter))
        if not rows:
            out[prefix] = {}  # 该季未披露：如实留空，不补零
            continue
        row = rows[0]
        out[prefix] = {k: v for k, v in row.items() if k not in ("code", "pubDate", "statDate")}
        if "pubDate" in row:
            out.setdefault("pub_date", row["pubDate"])
        if "statDate" in row:
            out.setdefault("stat_date", row["statDate"])
    logger.info(f"[BaoStock] 季频财务 {code} {year}Q{quarter} 完成")
    return {"status": "success", "source": "baostock", "symbol": code, "year": year, "quarter": quarter, "data": out}


def get_adjust_factor(symbol: str, *, start_date: str = "", end_date: str = "") -> dict[str, Any]:
    """复权因子（前/后复权因子原始值——比各家自算复权可信，可作 K 线仓库基准）。"""
    code = normalize_bs_code(symbol)
    bs = _ensure_login()
    rows = safe_query(bs, "query_adjust_factor", code, start_date or "1990-01-01", end_date or "2100-01-01")
    return {"status": "success", "source": "baostock", "symbol": code, "data": rows}


def get_stock_basic(symbol: str) -> dict[str, Any]:
    """单票基础信息（ipoDate/outDate/type/status）。"""
    code = normalize_bs_code(symbol)
    bs = _ensure_login()
    rows = safe_query(bs, "query_stock_basic", code)
    if not rows:
        return {"status": "error", "source": "baostock", "message": f"未查到 {code}"}
    return {"status": "success", "source": "baostock", "symbol": code, "data": rows[0]}
