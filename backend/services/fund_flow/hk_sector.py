"""港股南向资金行业分布 (AKShare 东方财富)

数据来源: 东方财富港股通行业资金流
接口: ak.stock_hsgt_fund_flow_summary_em() 或板块排名
频率: 日频 (盘后更新)
"""

import json
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.services.datasource.router import data_source_router

# Redis 缓存配置
_CACHE_KEY = "quant:fund_flow:hk_sector"
_CACHE_TTL = 600  # 10 分钟 (日频数据)


async def get_hk_sector_flow() -> dict[str, Any]:
    """
    获取港股南向资金行业分布（远程调用 AKShare 子服务，本地已移除 akshare SDK）。

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "HK",
            "market_name": "港股南向",
            "sectors": [
                {"name": "科技", "net_inflow": 12345.67, "pct": 0.35},
                ...
            ],
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
        logger.warning(f"[FundFlow] 港股板块缓存读取失败: {e}")

    # 2. 远程调用 AKShare 子服务（解析逻辑已下沉 data_subservice）
    try:
        result = await data_source_router.fetch_akshare("SECTOR_FLOW_HK")
        if result.get("status") != "success":
            raise ValueError(result.get("message", "远程港股行业资金流返回非成功状态"))

        result["data"]["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result, ensure_ascii=False), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[FundFlow] 港股板块缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[FundFlow] 港股南向行业资金流获取失败: {e}", exc_info=True)
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
        "message": f"港股南向行业数据暂不可用: {reason}",
        "data": {
            "market": "HK",
            "market_name": "港股南向",
            "sectors": [],
            "note": "日频更新，盘后刷新",
        },
    }
