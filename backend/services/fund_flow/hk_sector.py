"""港股行业板块资金流 (Futu 板块聚合)

数据来源: Futu 港股行业板块 (get_plate_list INDUSTRY) → 龙头成分股资金流聚合
接口: HK_SECTOR_FLOW (data_subservice futu_worker)
频率: 盘中聚合, 强缓存 30 分钟
"""

import json
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.services.datasource.router import data_source_router

# Redis 缓存配置
_CACHE_KEY = "quant:fund_flow:hk_sector"
_CACHE_TTL = 1800  # 30 分钟 (聚合开销大, 强缓存)


async def get_hk_sector_flow() -> dict[str, Any]:
    """
    获取港股行业板块资金流（Futu 板块聚合）。

    返回格式:
    {
        "status": "success" | "degraded",
        "data": {
            "market": "HK",
            "market_name": "港股行业板块",
            "sectors": [
                {"name": "金融", "net_inflow": 12345.67, "pct": 0.35},
                ...
            ],
            "unit": "港元",
            "updated_at": "...",
            "note": "...",
            "source": "Futu"
        }
    }
    """
    # 1. 检查缓存
    try:
        cached = await redis_client.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[FundFlow] 港股板块缓存读取失败: {e}")

    # 2. 远程调用 Futu 子服务港股板块资金流聚合
    try:
        result = await data_source_router.fetch_futu("HK_SECTOR_FLOW")
        if result.get("status") != "success":
            raise ValueError(result.get("message", "Futu 港股板块资金流返回非成功状态"))

        result["data"]["updated_at"] = datetime.now(timezone.utc).isoformat()
        result["data"]["source"] = "Futu"

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result, ensure_ascii=False), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[FundFlow] 港股板块缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[FundFlow] 港股板块资金流获取失败: {e}", exc_info=True)
        # 降级: 尝试返回 STALE 缓存
        try:
            stale = await redis_client.get(_CACHE_KEY)
            if stale:
                data = json.loads(stale)
                data["stale"] = True
                return data
        except Exception:
            pass
        return _fallback_result(str(e))


def _fallback_result(reason: str) -> dict[str, Any]:
    """降级: 返回 STALE 缓存或错误"""
    return {
        "status": "degraded",
        "message": f"港股行业板块资金流暂不可用: {reason}",
        "data": {
            "market": "HK",
            "market_name": "港股行业板块",
            "sectors": [],
            "note": "港股行业板块资金流暂不可用",
        },
    }
