"""美股主力/大单资金净流入 (Futu 资金分布代理)

数据来源: Futu get_capital_distribution (经 market_data.get_fund_flow 暴露的
          main_fund_net_inflow = 超大单 + 大单 净流入净额)。
实现: 复用后台实时引擎 manager.flow_cache 中已抓取的核心行业 ETF 资金分布
      (与 us_sector 同源, 避免重复触发 Futu 串行限流), 聚合得到美股主力/大单净流向。
      若缓存缺失则回退到 market_data.get_fund_flow 实时拉取。

说明: 本版本 AKShare 无美股大单/资金流接口, Futu OpenQuoteContext 亦无
      get_rt_big_order, 故以核心行业 ETF 的 Futu 资金分布(主力=超大单+大单)
      作为美股大单净流向的真实代理, 而非编造逐笔大单数据。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 与 us_sector 一致的核心行业 ETF 代理池 (Futu 代码)
_US_BIG_ORDER_UNIVERSE = [
    "US.SPY",
    "US.QQQ",
    "US.SOXX",
    "US.XLF",
    "US.XLE",
    "US.XLV",
    "US.KWEB",
    "US.TLT",
]
_US_BIG_ORDER_NAMES = {
    "US.SPY": "标普500",
    "US.QQQ": "纳斯达克100",
    "US.SOXX": "半导体ETF",
    "US.XLF": "金融ETF",
    "US.XLE": "能源ETF",
    "US.XLV": "医疗ETF",
    "US.KWEB": "中概互联",
    "US.TLT": "20年+国债",
}


async def get_us_big_order_flow() -> Dict[str, Any]:
    """聚合美股核心 ETF 的 Futu 主力/大单资金净流入。

    返回:
    {
        "status": "success",
        "data": {
            "total_net_inflow": -12.34,   # 亿美元 (超大单+大单 净买额合计)
            "unit": "亿美元",
            "breakdown": [
                {"ticker": "US.SPY", "name": "标普500", "net_inflow": 5.6},
                ...
            ],
            "note": "..."
        },
        "source": "futu-capital-distribution"
    }
    """
    from backend.app.macro_app import manager, market_data

    try:
        flows = []
        for ticker in _US_BIG_ORDER_UNIVERSE:
            # 💡 优先读实时引擎缓存, 回退 Futu 实时拉取
            raw = manager.flow_cache.get(ticker) or await market_data.get_fund_flow(ticker)
            if not raw:
                continue
            data = raw.get("data") or {}
            net = data.get("main_fund_net_inflow")
            if net is None:
                continue
            try:
                net = float(net)
            except (ValueError, TypeError):
                continue
            # 合理性边界：单 ETF 净流入超过 1 万亿（元）视为脏数据，跳过避免污染聚合。
            if abs(net) > 1e12:
                logger.warning(f"[BigOrder] {ticker} 净流入异常 {net:.2e} 元，超过 1 万亿边界，已跳过")
                continue
            flows.append({"ticker": ticker, "name": _US_BIG_ORDER_NAMES.get(ticker, ticker), "net": net})

        if not flows:
            return {
                "status": "warning",
                "message": "美股大单资金分布暂无可用数据 (Futu 未连接或 ETF 资金分布为空)",
                "data": None,
                "source": "futu-unavailable",
            }

        # 按 |净额| 降序, 突出贡献最大的标的
        flows.sort(key=lambda x: abs(x["net"]), reverse=True)
        total = sum(f["net"] for f in flows)
        breakdown = [{"ticker": f["ticker"], "name": f["name"], "net_inflow": round(f["net"] / 1e8, 2)} for f in flows]
        result = {
            "status": "success",
            "data": {
                "total_net_inflow": round(total / 1e8, 2),
                "unit": "亿美元",
                "breakdown": breakdown,
                "note": (
                    "基于核心行业 ETF(标普/纳指/半导体/金融/能源/医疗/中概/长债)的 Futu 主力(超大单+大单)资金分布聚合"
                ),
            },
            "source": "futu-capital-distribution",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("美股大单资金流聚合失败: %s", e)
        result = {
            "status": "warning",
            "message": "美股大单资金流聚合失败，暂无可用数据",
            "data": None,
            "source": "futu-unavailable",
        }
    return result
