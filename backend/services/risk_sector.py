"""
RISK-01: 板块暴露分析
按 GICS 标准聚合持仓行业分类，输出板块集中度
"""

import json
import time
from typing import Any, Dict, List, Optional

from backend.core.logger import logger
from backend.core.redis_client import redis_client

# GICS 11 大板块标准名称映射
GICS_SECTOR_MAP = {
    # 英文 → 中文
    "Technology": "科技",
    "Financials": "金融",
    "Healthcare": "医疗",
    "Consumer Discretionary": "可选消费",
    "Consumer Staples": "必选消费",
    "Industrials": "工业",
    "Energy": "能源",
    "Materials": "材料",
    "Real Estate": "房地产",
    "Utilities": "公用事业",
    "Communication Services": "通信服务",
    # 中文直接映射 (Futu 返回中文)
    "科技": "科技",
    "金融": "金融",
    "医疗": "医疗",
    "可选消费": "可选消费",
    "必选消费": "必选消费",
    "工业": "工业",
    "能源": "能源",
    "材料": "材料",
    "房地产": "房地产",
    "公用事业": "公用事业",
    "通信服务": "通信服务",
}


class SectorAnalyzer:
    """板块暴露分析器"""

    async def get_sector_exposure(
        self, positions: List[Dict], market: str = "HK"
    ) -> Dict[str, Any]:
        """
        获取持仓的板块暴露分布

        Returns:
            {sectors: [{sector, sector_cn, market_val, pct, symbols}], ts}
        """
        if not positions:
            return {"sectors": [], "ts": time.time()}

        # 1. 获取行业映射 (优先 Redis 缓存)
        sector_map = await self._get_sector_map(positions, market)

        # 2. 按板块聚合
        sector_agg: Dict[str, Dict[str, Any]] = {}
        total_nav = sum(float(p.get("market_val", 0)) for p in positions)

        for pos in positions:
            code = pos.get("code", "")
            mv = float(pos.get("market_val", 0))
            raw_sector = sector_map.get(code, "未知")
            sector_cn = GICS_SECTOR_MAP.get(raw_sector, raw_sector)

            if sector_cn not in sector_agg:
                sector_agg[sector_cn] = {"market_val": 0.0, "symbols": []}
            sector_agg[sector_cn]["market_val"] += mv
            sector_agg[sector_cn]["symbols"].append(code)

        # 3. 构建结果
        sectors = []
        for sector_name, data in sorted(sector_agg.items(), key=lambda x: -x[1]["market_val"]):
            pct = (data["market_val"] / total_nav * 100) if total_nav > 0 else 0
            sectors.append({
                "sector": sector_name,
                "market_val": round(data["market_val"], 2),
                "pct": round(pct, 2),
                "symbols": data["symbols"],
            })

        return {"sectors": sectors, "ts": time.time()}

    async def _get_sector_map(
        self, positions: List[Dict], market: str
    ) -> Dict[str, str]:
        """获取 code → sector 映射，优先 Redis 缓存"""
        codes = [p.get("code", "") for p in positions if p.get("code")]
        if not codes:
            return {}

        # 尝试读缓存
        cache_key = f"quant:risk:sector_map:{market}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                cached_map = json.loads(cached)
                # 检查是否覆盖所有持仓
                if all(c in cached_map for c in codes):
                    return cached_map
        except Exception:
            pass

        # 缓存未命中或不完整 → 从数据源获取
        sector_map: Dict[str, str] = {}

        # 优先 Futu get_stock_basicinfo
        try:
            from backend.services.futu_service import futu_service

            futu_market = "HK" if market == "HK" else "US"
            res = await futu_service.get_stock_basicinfo(futu_market, "STOCK")
            if res.get("status") == "success" and res.get("data"):
                for item in res["data"]:
                    code = item.get("code", "")
                    industry = item.get("industry", "") or item.get("sector", "")
                    if code and industry:
                        sector_map[code] = industry
        except Exception as e:
            logger.warning(f"[SectorAnalyzer] Futu basicinfo 获取失败: {e}")

        # 缺失的 → YFinance 兜底 (仅美股)
        missing = [c for c in codes if c not in sector_map]
        if missing and market == "US":
            try:
                import yfinance as yf

                for code in missing:
                    try:
                        info = yf.Ticker(code).info
                        sector = info.get("sector", "")
                        if sector:
                            sector_map[code] = sector
                    except Exception:
                        continue
            except Exception as e:
                logger.warning(f"[SectorAnalyzer] YFinance 兜底失败: {e}")

        # 仍未覆盖 → 标记未知
        for c in codes:
            if c not in sector_map:
                sector_map[c] = "未知"

        # 写缓存 (24h)
        try:
            await redis_client.set(cache_key, json.dumps(sector_map), ex=86400)
        except Exception as e:
            logger.warning(f"[SectorAnalyzer] 缓存写入失败: {e}")

        return sector_map


sector_analyzer = SectorAnalyzer()
