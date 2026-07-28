"""港股融资融券 / 卖空指标 (HKEX + SFC 监管底层)

数据来源：HKEX 每日卖空成交报表 + SFC 每周淡仓申报（市场级聚合）。
经 backend.services.margin.sources 编排器获取真实数据，绝不写假数据；
未配置监管文件 URL 或拉取失败时返回 error 状态由上层兜底。
"""

from datetime import date, datetime, timezone
from typing import Any, Dict

from backend.services.margin.sources.base import (
    get_market_margin_indicators as _fetch_market_margin,
)


async def get_hk_share_margin() -> Dict[str, Any]:
    """
    获取港股融资融券 / 卖空市场级指标（真实 HKEX/SFC 数据源）。

    返回:
        {"status": "success", "data": {...}} 或 {"status": "error", "data": None}
    """
    raw = await _fetch_market_margin("HK", date.today())
    if raw.get("status") == "error":
        return {"status": "error", "message": raw.get("message", "港股数据不可用"), "data": None}

    data = {
        "market": "HK_SHARE",
        "market_name": "港股",
        "as_of": raw.get("as_of"),
        "short_sale_volume": raw.get("short_sale_volume"),
        "total_volume": raw.get("total_volume"),
        "short_volume_ratio": raw.get("short_volume_ratio"),
        "short_interest_shares": raw.get("short_interest_shares"),
        "short_interest_ratio": raw.get("short_interest_ratio"),
        "financing_balance": raw.get("financing_balance"),
        "securities_balance": raw.get("securities_balance"),
        "sources": raw.get("sources", []),
        "note": raw.get("note", ""),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"status": "success", "data": data}
