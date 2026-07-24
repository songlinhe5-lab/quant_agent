"""美股板块 ETF 资金流代理 (Futu API)

数据来源: Futu 资金流接口 (核心行业 ETF)
标的: SPY/QQQ/SOXX/XLF/XLE/XLV/KWEB 等
频率: 盘中实时 (从 manager.flow_cache 读取)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.core.logger import logger

# 核心行业 ETF 映射
_SECTOR_ETFS = {
    "US.SPY": {"name": "标普500", "sector": "大盘"},
    "US.QQQ": {"name": "纳斯达克100", "sector": "科技"},
    "US.SOXX": {"name": "半导体ETF", "sector": "半导体"},
    "US.XLF": {"name": "金融ETF", "sector": "金融"},
    "US.XLE": {"name": "能源ETF", "sector": "能源"},
    "US.XLV": {"name": "医疗ETF", "sector": "医疗"},
    "US.KWEB": {"name": "中概互联", "sector": "中概股"},
    "US.TLT": {"name": "20年+国债", "sector": "债券"},
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
        from backend.routers.macro import manager, market_data

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
            net_inflow = 0.0
            if isinstance(data, dict):
                # 尝试多种字段名
                for key in ["net_inflow", "net_amount", "capital_flow"]:
                    if key in data:
                        net_inflow = float(data[key])
                        break
                # Futu 返回的可能是嵌套结构
                if net_inflow == 0 and "capital_flow" in data:
                    flow_data = data["capital_flow"]
                    if isinstance(flow_data, dict):
                        net_inflow = float(flow_data.get("net_amount", 0))

            # 转换为亿美元
            net_inflow_yi = round(net_inflow / 1e8, 2) if abs(net_inflow) > 1e6 else round(net_inflow, 2)

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
