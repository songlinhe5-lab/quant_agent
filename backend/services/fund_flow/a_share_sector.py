"""A 股板块资金流 (AKShare 东方财富)

数据来源: 东方财富行业/概念板块资金流排名
接口: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
频率: 盘中实时
"""

import json
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.services.datasource.router import data_source_router

# Redis 缓存配置
_CACHE_KEY = "quant:fund_flow:a_share_sector"
_CACHE_TTL = 300  # 5 分钟


def _safe_float(v) -> float | None:
    """安全转 float，None/非法值返回 None（前端展示 '--'）。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def get_a_share_sector_flow() -> dict[str, Any]:
    """
    获取 A 股行业板块资金流排名（远程调用 AKShare 子服务，本地已移除 akshare SDK）。

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "A_SHARE",
            "market_name": "A股行业",
            "inflow_top": [...],    # Top 10 净流入
            "outflow_top": [...],   # Top 5 净流出
            "updated_at": "...",
            "source": "AKShare (东方财富)"
        }
    }
    """
    # 1. 检查缓存
    try:
        cached = await redis_client.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[FundFlow] A股板块缓存读取失败: {e}")

    # 2. 远程调用 AKShare 子服务（解析逻辑已下沉 data_subservice）
    try:
        result = await data_source_router.fetch_akshare("SECTOR_FLOW_A")
        if result.get("status") != "success":
            raise ValueError(result.get("message", "远程A股板块资金流返回非成功状态"))

        # 统一为前端期望的 sectors 数组（与 hk/us 一致）：合并净流入+净流出榜，
        # 字段对齐 net_inflow/change_pct。子服务返回 inflow_top/outflow_top（main_net_inflow 正负混合）。
        _rd = result.get("data") or {}
        _in = _rd.get("inflow_top") or []
        _out = _rd.get("outflow_top") or []
        _sectors = []
        for _it in list(_in) + list(_out):
            _n = _it.get("name")
            if not _n:
                continue
            _sectors.append(
                {
                    "name": _n,
                    "net_inflow": _safe_float(_it.get("main_net_inflow")),
                    "change_pct": _safe_float(_it.get("change_pct")),
                }
            )
        _rd["sectors"] = _sectors
        _rd["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result, ensure_ascii=False), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[FundFlow] A股板块缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[FundFlow] A股板块资金流获取失败: {e}", exc_info=True)
        # 降级: 尝试返回 STALE 缓存
        try:
            stale = await redis_client.get(_CACHE_KEY)
            if stale:
                data = json.loads(stale)
                data["stale"] = True
                return data
        except Exception:
            pass
        return {"status": "error", "message": f"A股板块资金流获取失败: {e}", "data": None}
