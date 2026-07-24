"""港股南向资金行业分布 (AKShare 东方财富)

数据来源: 东方财富港股通行业资金流
接口: ak.stock_hsgt_fund_flow_summary_em() 或板块排名
频率: 日频 (盘后更新)
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# Redis 缓存配置
_CACHE_KEY = "quant:fund_flow:hk_sector"
_CACHE_TTL = 600  # 10 分钟 (日频数据)


async def get_hk_sector_flow() -> dict[str, Any]:
    """
    获取港股南向资金行业分布

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

    # 2. 从 AKShare 获取数据
    try:
        import akshare as ak

        # 尝试获取港股通行业资金流数据
        df = await asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em)

        if df is None or df.empty:
            return _fallback_result("AKShare 返回空数据")

        # 解析南向资金行业分布
        sectors = _parse_hk_sector_data(df)

        if not sectors:
            return _fallback_result("无法解析港股行业数据")

        result = {
            "status": "success",
            "data": {
                "market": "HK",
                "market_name": "港股南向",
                "sectors": sectors,
                "unit": "万元",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "AKShare (东方财富)",
                "note": "日频更新，盘后刷新",
            },
        }

        # 3. 写入缓存
        try:
            await redis_client.set(_CACHE_KEY, json.dumps(result, ensure_ascii=False), ex=_CACHE_TTL)
        except Exception as e:
            logger.warning(f"[FundFlow] 港股板块缓存写入失败: {e}")

        return result

    except Exception as e:
        logger.error(f"[FundFlow] 港股南向行业资金流获取失败: {e}", exc_info=True)
        return _fallback_result(str(e))


def _parse_hk_sector_data(df) -> list[dict]:
    """解析港股通行业资金流数据"""
    sectors = []

    # 东方财富港股通行业字段映射
    name_candidates = ["行业", "板块名称", "名称"]
    flow_candidates = ["净买入", "资金净流入", "净买入额", "今日主力净流入-净额"]

    name_col = None
    flow_col = None
    for col in df.columns:
        if name_col is None and any(c in col for c in name_candidates):
            name_col = col
        if flow_col is None and any(c in col for c in flow_candidates):
            flow_col = col

    if name_col is None or flow_col is None:
        # 尝试通用解析: 第一列为名称，找数值列
        cols = df.columns.tolist()
        if len(cols) >= 2:
            name_col = cols[0]
            for col in cols[1:]:
                try:
                    df[col] = df[col].astype(float)
                    flow_col = col
                    break
                except (ValueError, TypeError):
                    continue

    if name_col is None or flow_col is None:
        return []

    df[flow_col] = df[flow_col].astype(float)
    df_sorted = df.sort_values(flow_col, ascending=False)

    total_abs = df_sorted[flow_col].abs().sum()
    for _, row in df_sorted.head(15).iterrows():
        net = float(row[flow_col])
        sectors.append(
            {
                "name": str(row[name_col]),
                "net_inflow": round(net / 1e4, 2),  # 万元
                "pct": round(net / total_abs, 4) if total_abs > 0 else 0,
            }
        )

    return sectors


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
