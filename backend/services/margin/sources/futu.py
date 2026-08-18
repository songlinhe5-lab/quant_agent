"""
港股卖空成交占比 —— Futu OpenD 兜底源（经主服务 DataSourceRouter 远程调用）。

背景：港股市场级卖空指标优先走 HKEX 每日卖空成交报表 + SFC 每周淡仓申报
（监管底层 CSV，见 hkex.py / sfc.py）。当这两个监管源未配置真实文件 URL
或拉取失败时，本源作为兜底，经 data_subservice（主节点持有 OpenD 长连接）
的 ``get_short_selling_rank`` 拿港股卖空成交榜，再**真实聚合**成市场级占比：

    short_volume_ratio = Σ(个股 short_sell_volume) / Σ(个股 volume) × 100

这是可被计算的市场级指标（榜内汇总），非编造。仅作兜底，不覆盖监管源。

红线（呼应 AGENTS.md）：主服务不得直接 ``from futu import``，必须经
DataSourceRouter.fetch_futu 远程调用 data_subservice，绝不在本模块持有 SDK。
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import List, Optional

import structlog

from backend.services.datasource.router import data_source_router
from backend.services.margin.sources.base import (
    BaseMarginSource,
    MarketMarginSnapshot,
)

logger = structlog.get_logger(__name__)

_FUTU_SHORT_SELLING_TIMEOUT = 25  # 秒；futu 内部重连不抛异常，靠外层 wait_for 兜底防挂死


class FutuShortSellingSource(BaseMarginSource):
    """港股卖空成交占比兜底源（Futu 卖空榜聚合）。

    仅当 HKEX/SFC 监管源失败时由编排器链式尝试；返回真实可算的市场级占比，
    绝不编造数字。
    """

    name = "futu_short_selling"
    market = "HK"

    async def fetch(self, as_of: date) -> Optional[MarketMarginSnapshot]:
        try:
            result = await asyncio.wait_for(
                data_source_router.fetch_futu("short_selling", market="HK", count=50),
                timeout=_FUTU_SHORT_SELLING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("[Margin][futu_short_selling] 远程调用超时", market="HK")
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("[Margin][futu_short_selling] 远程调用异常", error=str(e))
            return None

        if not isinstance(result, dict) or result.get("status") != "success":
            logger.debug(
                "[Margin][futu_short_selling] 无可用数据",
                status=result.get("status") if isinstance(result, dict) else type(result),
                message=result.get("message") if isinstance(result, dict) else None,
            )
            return None

        rows: List[dict] = result.get("data") or []
        if not rows:
            return None

        total_short = 0.0
        total_volume = 0.0
        for r in rows:
            sv = r.get("short_sell_volume")
            vol = r.get("volume")
            if isinstance(sv, (int, float)) and isinstance(vol, (int, float)) and vol > 0:
                total_short += float(sv)
                total_volume += float(vol)

        if total_volume <= 0:
            logger.debug("[Margin][futu_short_selling] 榜内成交量合计为 0，无法聚合占比")
            return None

        ratio = total_short / total_volume * 100.0
        return MarketMarginSnapshot(
            market="HK",
            as_of=as_of.isoformat(),
            short_sale_volume=round(total_short, 2),
            total_volume=round(total_volume, 2),
            short_volume_ratio=round(ratio, 4),
            sources=["futu"],
            note="港股卖空成交占比由 Futu 卖空榜聚合得出（HKEX/SFC 监管源不可用时兜底）",
        )
