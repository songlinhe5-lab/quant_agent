"""美股融资融券数据获取 (FINRA / YFinance)

数据来源: FINRA Margin Statistics / YFinance
接口: FINRA API (月度数据) 或 YFinance (个股保证金数据)
频率: 月度 (FINRA) / 实时 (YFinance)
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# Redis 缓存配置
_CACHE_KEY = "quant:margin:us_share"
_CACHE_TTL = 300  # 5 分钟


async def get_us_share_margin() -> Dict[str, Any]:
    """
    获取美股融资融券余额数据

    方案 A: FINRA Margin Statistics (免费，月度数据)
    - 网址: https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics
    - 数据: 全市场融资余额 (Margin Debt)
    - 频率: 月度更新

    方案 B: YFinance (个股保证金数据)
    - 接口: ticker.info['marginData']
    - 数据: 个股级别的保证金要求
    - 频率: 实时

    当前实现: 使用 FINRA 月度数据 + Mock 补充

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "US_SHARE",
            "market_name": "美股",
            "financing_balance": 8234.56,  # 融资余额（亿美元）
            "securities_balance": 0.0,     # 融券余额（美股无统一融券余额数据）
            "financing_change": +123.45,
            "securities_change": 0.0,
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
        logger.warning(f"[Margin] 美股缓存读取失败: {e}")

    # 2. 尝试获取数据
    try:
        # TODO: 接入 FINRA API 获取真实 Margin Debt 数据
        # FINRA 提供月度 Margin Statistics，可爬取或调用 API
        # 当前使用 Mock 数据作为占位

        # 临时使用 Mock 数据（实际部署时应替换为真实数据）
        result = {
            "status": "success",
            "data": {
                "market": "US_SHARE",
                "market_name": "美股",
                "financing_balance": 8562.34,  # 亿美元 (FINRA Margin Debt)
                "securities_balance": 0.0,  # 美股无统一融券余额数据
                "financing_change": +85.67,
                "securities_change": 0.0,
                "unit": "亿美元",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "FINRA Margin Statistics (Mock)",
                "note": "美股融券余额数据需接入 SEC 或交易所数据源",
            },
        }

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[Margin] 美股缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[Margin] 美股数据获取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"美股数据获取失败: {str(e)}",
            "data": None,
        }
