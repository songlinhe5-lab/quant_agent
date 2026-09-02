"""TDX 查询服务：盘中快照 / 分时 / 分钟线与日线增量（tdxpy 直连）。

返回原始行列表经 api.to_df 转 DataFrame，统一转 records + source 标注。
空结果不是错误（停牌/非交易时段），如实返回空列表；None 是协议异常。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from data_subservice._internal.logger import logger
from data_subservice._internal.tdx.client import FREQ_MAP, normalize_tdx_symbol, to_market, with_tdx

_MAX_BARS_PER_CALL = 800  # TDX 协议单次 K 线上限，超出由调用方分页


def _df_payload(symbol: str, action: str, df: pd.DataFrame | None) -> dict[str, Any]:
    if df is None:
        raise RuntimeError(f"TDX {action} 返回 None（连接或服务器异常）")
    records = df.to_dict("records") if not df.empty else []
    # 统一 JSON 安全（Timestamp 等出口由 main._json_safe 再兜一层）
    return {"status": "success", "source": "tdx", "symbol": symbol, "action": action, "data": records}


def get_snapshot(symbol: str) -> dict[str, Any]:
    """实时快照（盘中 3 秒级；非交易时段返回最近快照，servertime 字段可判新旧）。"""
    code = normalize_tdx_symbol(symbol)
    mkt = to_market(code)

    def _do(api: Any) -> pd.DataFrame | None:
        raw = api.get_security_quotes([(mkt, code)])
        if raw is None:
            return None
        return api.to_df(raw) if raw else pd.DataFrame()

    payload = _df_payload(code, "SNAPSHOT", with_tdx(_do))
    logger.debug(f"[TDX] 快照 {code}: {len(payload['data'])} 行")
    return payload


def get_bars(symbol: str, *, frequency: str = "day", offset: int = 100) -> dict[str, Any]:
    """K 线增量（5/15/30/60 分钟 + 日/周/月）；分钟线盘中滚动更新（与 baostock 历史首尾相接）。"""
    code = normalize_tdx_symbol(symbol)
    mkt = to_market(code)
    freq = FREQ_MAP.get(str(frequency).lower())
    if freq is None:
        raise ValueError(f"不支持的 K 线周期: {frequency}（5m/15m/30m/60m/day/week/month）")
    count = max(1, min(int(offset), _MAX_BARS_PER_CALL))

    def _do(api: Any) -> pd.DataFrame | None:
        raw = api.get_security_bars(freq, mkt, code, 0, count)
        if raw is None:
            return None
        return api.to_df(raw) if raw else pd.DataFrame()

    payload = _df_payload(code, f"BARS_{freq}", with_tdx(_do))
    payload["frequency"] = str(frequency).lower()
    payload["offset"] = count
    return payload


def get_minutes(symbol: str, *, date: str = "") -> dict[str, Any]:
    """分时数据（当日，或指定历史交易日 yyyymmdd 走历史分时接口）。"""
    code = normalize_tdx_symbol(symbol)
    mkt = to_market(code)
    day = date.replace("-", "") if date else ""

    def _do(api: Any) -> pd.DataFrame | None:
        raw = api.get_history_minute_time_data(mkt, code, day) if day else api.get_minute_time_data(mkt, code)
        if raw is None:
            return None
        return api.to_df(raw) if raw else pd.DataFrame()

    return _df_payload(code, "MINUTES", with_tdx(_do))
