"""美股 GICS 行业板块资金流代理 (Futu API)

数据来源: Futu 资金流接口 (标准 GICS 11 大行业 SPDR ETF)
标的: XLK/XLF/XLV/XLY/XLP/XLE/XLI/XLB/XLC/XLU/XLRE
频率: 盘中实时 (优先从 manager.flow_cache 读取，miss 时实时调用)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger

# 标准 GICS 11 大行业板块 → SPDR 行业 ETF 代理映射
# 每个行业用对应的 Sector SPDR ETF 获取主力资金流（Futu FUND_FLOW）
_SECTOR_ETFS = {
    "US.XLK": {"name": "科技", "sector": "信息技术"},
    "US.XLF": {"name": "金融", "sector": "金融"},
    "US.XLV": {"name": "医疗", "sector": "医疗保健"},
    "US.XLY": {"name": "可选消费", "sector": "可选消费"},
    "US.XLP": {"name": "必选消费", "sector": "必选消费"},
    "US.XLE": {"name": "能源", "sector": "能源"},
    "US.XLI": {"name": "工业", "sector": "工业"},
    "US.XLB": {"name": "材料", "sector": "原材料"},
    "US.XLC": {"name": "通信", "sector": "通信服务"},
    "US.XLU": {"name": "公用事业", "sector": "公用事业"},
    "US.XLRE": {"name": "地产", "sector": "房地产"},
}


async def get_us_sector_flow() -> dict[str, Any]:
    """
    获取美股板块 ETF 资金流

    返回格式:
    {
        "status": "success",
        "data": {
            "market": "US",
            "market_name": "美股板块",
            "sectors": [
                {"ticker": "US.SPY", "name": "标普500", "sector": "大盘",
                 "net_inflow": 123.45, "unit": "亿美元", "dir": 1},
                ...
            ],
            "updated_at": "...",
            "source": "Futu API"
        }
    }
    """
    try:
        from backend.app.macro_app import manager, market_data

        async def _get_flow(ticker: str) -> dict:
            """优先从后台缓存读取，避免 Futu 限流"""
            if ticker in manager.flow_cache:
                return manager.flow_cache[ticker]
            return await market_data.get_fund_flow(ticker)

        # 并发获取所有 ETF 资金流
        tickers = list(_SECTOR_ETFS.keys())
        results = await asyncio.gather(
            *[_get_flow(t) for t in tickers],
            return_exceptions=True,
        )

        sectors = []
        for ticker, res in zip(tickers, results):
            if isinstance(res, BaseException):
                logger.warning(f"[FundFlow] {ticker} 资金流获取失败: {res}")
                continue

            info = _SECTOR_ETFS[ticker]
            data = res.get("data", {}) if isinstance(res, dict) else {}

            # 解析 Futu 资金流数据
            # 子服务 FUND_FLOW 仅返回 main_fund_net_inflow（主力净流入，单位：元）。
            # 只信任该权威字段，避免历史缓存残留的 net_inflow/net_amount 错结构污染。
            # res 顶层与 data 内层都可能有该键（Router 封装差异），优先取非空数值。
            net_inflow = 0.0
            for src in (res if isinstance(res, dict) else {}, data if isinstance(data, dict) else {}):
                if "main_fund_net_inflow" in src and isinstance(src["main_fund_net_inflow"], (int, float)):
                    v = float(src["main_fund_net_inflow"])
                    if v != 0:
                        net_inflow = v
                        break

            # 合理性边界：单 ETF 主力净流入超过 1 万亿（元）视为脏数据，降级为 0 并告警。
            # 美股单只 ETF 日级主力净流入通常在 ±数十亿美元量级，异常大数必为上游单位错乱。
            if abs(net_inflow) > 1e12:
                logger.warning(
                    f"[FundFlow] {ticker} 净流入异常 {net_inflow:.2e} 元，超过 1 万亿边界，疑似上游单位错乱，已降级为 0"
                )
                net_inflow = 0.0

            # 上游已统一为「元」，直接换算为亿美元
            net_inflow_yi = round(net_inflow / 1e8, 2)

            sectors.append(
                {
                    "ticker": ticker,
                    "name": info["name"],
                    "sector": info["sector"],
                    "net_inflow": net_inflow_yi,
                    "unit": "亿美元",
                    "dir": 1 if net_inflow_yi >= 0 else -1,
                }
            )

        # 按净流入排序
        sectors.sort(key=lambda x: x["net_inflow"], reverse=True)

        return {
            "status": "success",
            "data": {
                "market": "US",
                "market_name": "美股板块",
                "sectors": sectors,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "source": "Futu API",
            },
        }

    except Exception as e:
        logger.error(f"[FundFlow] 美股板块资金流获取失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"美股板块资金流获取失败: {e}",
            "data": None,
        }
