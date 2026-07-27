"""港股融资融券数据获取 (Futu API)

数据来源: Futu OpenD
接口: 港股市场融资融券数据
频率: 日频
"""

import json
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

        # 无真实数据源：港股融资融券 (Futu / 港交所披露易) 尚未接入，
        # 禁止返回写死假数据并写入缓存，统一返回错误状态由前端展示空/错误兜底。
        logger.warning("[Margin] 港股融资融券数据源尚未接入，返回空数据")
        return {
            "status": "error",
            "message": "港股融资融券数据源尚未接入，暂无可展示数据",
            "data": None,
        }

    except Exception as e:
        logger.error(f"[Margin] 港股数据获取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"港股数据获取失败: {str(e)}",
            "data": None,
        }
