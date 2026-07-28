"""美股融资融券 / 卖空指标 (FINRA 监管底层)

数据来源：FINRA Reg SHO 每日做空成交量 + Equity Short Interest（市场级聚合）。
经 backend.services.margin.sources 编排器获取真实数据，绝不写假数据；
无可用真实源时返回 error 状态由上层兜底。
"""

from datetime import date, datetime, timezone
from typing import Any, Dict

from backend.services.margin.sources.base import (
    get_market_margin_indicators as _fetch_market_margin,
)


async def get_us_share_margin() -> Dict[str, Any]:
    """
    获取美股融资融券 / 卖空市场级指标（真实 FINRA 数据源）。

    返回:
        {"status": "success", "data": {...}} 或 {"status": "error", "data": None}
    """
    raw = await _fetch_market_margin("US", date.today())
    if raw.get("status") == "error":
        return {"status": "error", "message": raw.get("message", "美股数据不可用"), "data": None}

    data = {
        "market": "US_SHARE",
        "market_name": "美股",
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
