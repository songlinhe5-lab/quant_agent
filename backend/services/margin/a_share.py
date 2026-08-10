"""A 股融资融券数据获取 (AKShare)

数据来源: 上交所/深交所融资融券数据
接口: ak.stock_margin_sse() / ak.stock_margin_szse()
频率: T+1 日更新
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.services.datasource.router import data_source_router

# Redis 缓存配置
_CACHE_KEY = "quant:margin:a_share"
_CACHE_TTL = 300  # 5 分钟


async def get_a_share_margin() -> Dict[str, Any]:
    """
    获取 A 股融资融券余额数据（远程调用 AKShare 子服务，本地已移除 akshare SDK）。

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "A_SHARE",
            "market_name": "A 股",
            "financing_balance": 15234.56,  # 融资余额（亿元）
            "securities_balance": 234.56,   # 融券余额（亿元）
            "financing_change": +12.34,     # 较前日变化（亿元）
            "securities_change": -5.67,
            "updated_at": "2026-07-22T10:00:00Z"
        }
    }
    """
    # 1. 检查缓存
    try:
        cached = await redis_client.get(_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"[Margin] A 股缓存读取失败: {e}")

    # 2. 远程调用 AKShare 子服务（解析逻辑已下沉 data_subservice）
    try:
        result = await data_source_router.fetch_akshare("MARGIN_A_SHARE")
        if result.get("status") != "success":
            raise ValueError(result.get("message", "远程融资融券返回非成功状态"))

        result["data"]["updated_at"] = datetime.now(timezone.utc).isoformat()

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result, ensure_ascii=False), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[Margin] A 股缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[Margin] A 股数据获取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"A 股数据获取失败: {str(e)}",
            "data": None,
        }
