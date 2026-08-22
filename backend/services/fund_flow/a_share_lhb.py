"""A股龙虎榜聚合 (FUNDFLOW-02)。

远程调用 AKShare 子服务的 LHB_DETAIL / LHB_STOCK_STAT，聚合成：
- 机构榜 (label == "机构") 与 游资榜 (label == "游资")
- 近 N 日净买额（取 LHB_STOCK_STAT 的区间净买额作为近似区间值）

返回结构与 macro_app._a_share_lhb 契约一致，带降级（无数据源时返回 None）。
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.core.redis_client import redis_client
from backend.services.datasource.data_source_router import data_source_router

_CACHE_TTL = 300
_CACHE_TTL_FAIL = 60


async def _fetch(action: str, cache_key: str, force_refresh: bool, **params) -> Dict[str, Any]:
    if not force_refresh:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    try:
        result = await data_source_router.fetch_akshare(action, **params)
        if result.get("status") != "success":
            raise ValueError(result.get("message", f"{action} 返回非成功状态"))
    except Exception as e:
        result = {
            "status": "warning",
            "message": f"龙虎榜获取失败（{action}）: {e}",
            "data": None,
            "source": "akshare-unavailable",
        }
    result["updated_at"] = datetime.now(timezone.utc).isoformat()
    ttl = _CACHE_TTL if result.get("status") == "success" else _CACHE_TTL_FAIL
    try:
        await redis_client.set(cache_key, json.dumps(result, default=str), ex=ttl)
    except Exception:
        pass
    return result


async def get_a_share_lhb(date: Optional[str] = None, force_refresh: bool = False) -> Dict[str, Any]:
    """A股龙虎榜：机构 vs 游资分组 + 区间净买额。

    返回:
    {
      "trade_date": str,
      "institution": [{"code","name","net_buy","period_net_buy","reason","label"}],
      "retail":     [{"code","name","net_buy","period_net_buy","reason","label"}],
      "unit": "元",
      "source": str,
    } | None
    """
    trade_date = date or datetime.now().strftime("%Y%m%d")
    detail = await _fetch("LHB_DETAIL", f"akshare_lhb_detail_{trade_date}", force_refresh, date=trade_date)
    items = (detail.get("data") or []) if detail.get("status") == "success" else []

    # 区间净买额（近一月统计，近似区间值）
    period_stat = await _fetch("LHB_STOCK_STAT", "akshare_lhb_stock_stat_近一月", force_refresh, period="近一月")
    stat_map = {}
    if period_stat.get("status") == "success":
        for s in period_stat.get("data") or []:
            stat_map[str(s.get("code"))] = _to_float(s.get("net_buy"))

    institution, retail = [], []
    for it in items:
        code = str(it.get("code") or "")
        entry = {
            "code": code,
            "name": it.get("name"),
            "net_buy": _to_float(it.get("net_buy")),
            "period_net_buy": stat_map.get(code, _to_float(it.get("net_buy"))),
            "reason": it.get("reason"),
            "label": it.get("label", "游资"),
        }
        if entry["label"] == "机构":
            institution.append(entry)
        else:
            retail.append(entry)

    institution.sort(key=lambda x: x["period_net_buy"], reverse=True)
    retail.sort(key=lambda x: x["period_net_buy"], reverse=True)

    payload = {
        "trade_date": trade_date,
        "institution": institution[:20],
        "retail": retail[:20],
        "unit": "元",
        "source": detail.get("source", "akshare"),
    }
    return payload


def _to_float(v: Any) -> float:
    try:
        if v is None or v == "" or v == "None":
            return 0.0
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0
