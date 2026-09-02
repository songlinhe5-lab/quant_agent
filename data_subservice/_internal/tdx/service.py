"""TDX 查询服务：盘中快照 / 分时 / 分钟线与日线增量。

mootdx 返回 pandas DataFrame；统一转 records + source 标注。
空 DataFrame 不是错误（停牌/非交易时段），如实返回空列表。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_subservice._internal.logger import logger
from data_subservice._internal.tdx.client import FREQ_MAP, call_client, normalize_tdx_symbol


def _df_payload(symbol: str, action: str, df: pd.DataFrame | None) -> dict[str, Any]:
    if df is None:
        raise RuntimeError(f"TDX {action} 返回 None（连接或服务器异常）")
    records = df.to_dict("records") if not df.empty else []
    # 统一 JSON 安全（Timestamp 等出口由 main._json_safe 再兜一层）
    return {"status": "success", "source": "tdx", "symbol": symbol, "action": action, "data": records}


def get_snapshot(symbol: str) -> dict[str, Any]:
    """实时快照（盘中 3 秒级；非交易时段返回最近快照，servertime 字段可判新旧）。"""
    code = normalize_tdx_symbol(symbol)
    df = call_client("quotes", symbol=code)
    payload = _df_payload(code, "SNAPSHOT", df)
    logger.debug(f"[TDX] 快照 {code}: {len(payload['data'])} 行")
    return payload


def get_bars(symbol: str, *, frequency: str = "day", offset: int = 100) -> dict[str, Any]:
    """K 线增量（1/5/15/30/60 分钟 + 日/周/月）；分钟线盘中滚动更新（与 baostock 历史首尾相接）。"""
    code = normalize_tdx_symbol(symbol)
    freq = FREQ_MAP.get(str(frequency).lower())
    if freq is None:
        raise ValueError(f"不支持的 K 线周期: {frequency}（5m/15m/30m/60m/day/week/month）")
    df = call_client("bars", symbol=code, frequency=freq, offset=int(offset))
    payload = _df_payload(code, f"BARS_{freq}", df)
    payload["frequency"] = str(frequency).lower()
    payload["offset"] = int(offset)
    return payload


def get_minutes(symbol: str, *, date: str = "") -> dict[str, Any]:
    """分时数据（当日或指定历史交易日）。"""
    code = normalize_tdx_symbol(symbol)
    df = call_client("minutes", symbol=code, date=date) if date else call_client("minutes", symbol=code)
    return _df_payload(code, "MINUTES", df)
