"""A 股板块资金流 (AKShare 东方财富)

数据来源: 东方财富行业/概念板块资金流排名
接口: ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
频率: 盘中实时
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# Redis 缓存配置
_CACHE_KEY = "quant:fund_flow:a_share_sector"
_CACHE_TTL = 300  # 5 分钟


async def get_a_share_sector_flow() -> dict[str, Any]:
    """
    获取 A 股行业板块资金流排名

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

    # 2. 从 AKShare 获取数据
    try:
        import akshare as ak

        df = await asyncio.to_thread(
            ak.stock_sector_fund_flow_rank,
            indicator="今日",
            sector_type="行业资金流",
        )

        if df is None or df.empty:
            return {"status": "error", "message": "AKShare 返回空数据", "data": None}

        # 解析字段 (东方财富字段名)
        name_col = "名称"
        change_col = "今日涨跌幅"
        main_net_col = "今日主力净流入-净额"
        main_pct_col = "今日主力净流入-净占比"

        # 兼容字段名差异
        if main_net_col not in df.columns:
            for col in df.columns:
                if "主力净流入" in col and "净额" in col:
                    main_net_col = col
                    break
        if main_pct_col not in df.columns:
            for col in df.columns:
                if "主力净流入" in col and "净占比" in col:
                    main_pct_col = col
                    break
        if change_col not in df.columns:
            for col in df.columns:
                if "涨跌幅" in col:
                    change_col = col
                    break

        # 确保主力净流入为数值
        df[main_net_col] = df[main_net_col].astype(float)
        df_sorted = df.sort_values(main_net_col, ascending=False)

        def _parse_row(row) -> dict:
            return {
                "name": str(row.get(name_col, "")),
                "change_pct": round(float(row.get(change_col, 0)), 2),
                "main_net_inflow": round(float(row.get(main_net_col, 0)) / 1e4, 2),  # 万元
                "main_net_pct": round(float(row.get(main_pct_col, 0)), 2),
            }

        inflow_top = [_parse_row(row) for _, row in df_sorted.head(10).iterrows()]
        outflow_top = [_parse_row(row) for _, row in df_sorted.tail(5).iloc[::-1].iterrows()]

        result = {
            "status": "success",
            "data": {
                "market": "A_SHARE",
                "market_name": "A股行业",
                "inflow_top": inflow_top,
                "outflow_top": outflow_top,
                "unit": "万元",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "AKShare (东方财富)",
            },
        }

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
