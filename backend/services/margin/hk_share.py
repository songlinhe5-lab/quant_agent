"""港股融资融券数据获取 (Futu API)

数据来源: Futu OpenD
接口: 港股市场融资融券数据
频率: 日频
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# Redis 缓存配置
_CACHE_KEY = "quant:margin:hk_share"
_CACHE_TTL = 300  # 5 分钟


async def get_hk_share_margin() -> Dict[str, Any]:
    """
    获取港股融资融券余额数据

    注意: Futu API 可能不直接提供全市场融资融券余额，
    此处使用 Mock 数据作为占位，后续可接入真实数据源。

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "HK_SHARE",
            "market_name": "港股",
            "financing_balance": 1234.56,  # 融资余额（亿港元）
            "securities_balance": 56.78,   # 融券余额（亿港元）
            "financing_change": +5.67,
            "securities_change": -1.23,
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
        logger.warning(f"[Margin] 港股缓存读取失败: {e}")

    # 2. 尝试从 Futu 获取数据
    try:
        # TODO: 接入 Futu API 获取真实融资融券数据
        # 目前 Futu OpenD 可能不直接提供全市场融资融券余额
        # 可考虑接入港交所披露易或其他数据源

        # 临时使用 Mock 数据（实际部署时应替换为真实数据）
        result = {
            "status": "success",
            "data": {
                "market": "HK_SHARE",
                "market_name": "港股",
                "financing_balance": 1580.25,  # 亿港元
                "securities_balance": 82.36,
                "financing_change": +12.58,
                "securities_change": -2.15,
                "unit": "亿港元",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "Futu API (Mock)",
            },
        }

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[Margin] 港股缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[Margin] 港股数据获取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"港股数据获取失败: {str(e)}",
            "data": None,
        }
