"""A 股融资融券数据获取 (AKShare)

数据来源: 上交所/深交所融资融券数据
接口: ak.stock_margin_sse() / ak.stock_margin_szse()
频率: T+1 日更新
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# Redis 缓存配置
_CACHE_KEY = "quant:margin:a_share"
_CACHE_TTL = 300  # 5 分钟


async def get_a_share_margin() -> Dict[str, Any]:
    """
    获取 A 股融资融券余额数据

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

    # 2. 从 AKShare 获取数据
    try:
        import akshare as ak

        # 并发获取上交所和深交所数据
        sse_df, szse_df = await asyncio.gather(
            asyncio.to_thread(ak.stock_margin_sse),
            asyncio.to_thread(ak.stock_margin_szse),
            return_exceptions=True,
        )

        # 解析上交所数据
        sse_financing = 0.0
        sse_securities = 0.0
        if not isinstance(sse_df, BaseException) and sse_df is not None and not sse_df.empty:
            # 取最新一行数据
            latest = sse_df.iloc[-1]
            # 字段名可能因 AKShare 版本而异，尝试常见字段名
            for col in ["融资余额", "融资余额 (元)", "financing_balance"]:
                if col in latest.index:
                    sse_financing = float(latest[col]) / 1e8  # 转换为亿元
                    break
            for col in ["融券余额", "融券余额 (元)", "securities_balance"]:
                if col in latest.index:
                    sse_securities = float(latest[col]) / 1e8
                    break

        # 解析深交所数据
        szse_financing = 0.0
        szse_securities = 0.0
        if not isinstance(szse_df, BaseException) and szse_df is not None and not szse_df.empty:
            latest = szse_df.iloc[-1]
            for col in ["融资余额", "融资余额 (元)", "financing_balance"]:
                if col in latest.index:
                    szse_financing = float(latest[col]) / 1e8
                    break
            for col in ["融券余额", "融券余额 (元)", "securities_balance"]:
                if col in latest.index:
                    szse_securities = float(latest[col]) / 1e8
                    break

        # 汇总两市数据
        total_financing = round(sse_financing + szse_financing, 2)
        total_securities = round(sse_securities + szse_securities, 2)

        # 计算变化量（如果有前一日数据）
        financing_change = 0.0
        securities_change = 0.0
        if not isinstance(sse_df, BaseException) and sse_df is not None and len(sse_df) >= 2:
            prev = sse_df.iloc[-2]
            for col in ["融资余额", "融资余额 (元)", "financing_balance"]:
                if col in prev.index:
                    prev_financing = float(prev[col]) / 1e8
                    financing_change = round(total_financing - prev_financing - szse_financing, 2)
                    break

        result = {
            "status": "success",
            "data": {
                "market": "A_SHARE",
                "market_name": "A 股",
                "financing_balance": total_financing,
                "securities_balance": total_securities,
                "financing_change": financing_change,
                "securities_change": securities_change,
                "unit": "亿元",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "AKShare (上交所/深交所)",
            },
        }

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result), ex=_CACHE_TTL)
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
