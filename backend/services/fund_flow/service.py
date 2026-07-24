"""板块资金流聚合服务

三市场并发获取，单市场失败不影响其他:
- A股行业 (AKShare 东方财富)
- 港股南向 (AKShare 东方财富)
- 美股板块 (Futu API ETF 代理)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any

from backend.services.fund_flow.a_share_sector import get_a_share_sector_flow
from backend.services.fund_flow.hk_sector import get_hk_sector_flow
from backend.services.fund_flow.us_sector import get_us_sector_flow


class FundFlowService:
    """板块资金流聚合服务"""

    async def get_sector_fund_flow(self) -> dict[str, Any]:
        """
        获取三市场板块资金流聚合数据

        返回格式:
        {
            "status": "success" | "partial" | "error",
            "data": {
                "a_share": {...},
                "hk": {...},
                "us": {...},
                "updated_at": "..."
            }
        }
        """
        a_share_task = get_a_share_sector_flow()
        hk_task = get_hk_sector_flow()
        us_task = get_us_sector_flow()

        results = await asyncio.gather(
            a_share_task,
            hk_task,
            us_task,
            return_exceptions=True,
        )

        a_share = (
            results[0] if not isinstance(results[0], BaseException) else {"status": "error", "message": str(results[0])}
        )
        hk = (
            results[1] if not isinstance(results[1], BaseException) else {"status": "error", "message": str(results[1])}
        )
        us = (
            results[2] if not isinstance(results[2], BaseException) else {"status": "error", "message": str(results[2])}
        )

        # 判断整体状态
        statuses = [r.get("status") for r in [a_share, hk, us] if isinstance(r, dict)]
        success_count = sum(1 for s in statuses if s in ("success", "degraded"))

        if success_count == 3:
            overall_status = "success"
        elif success_count > 0:
            overall_status = "partial"
        else:
            overall_status = "error"

        return {
            "status": overall_status,
            "data": {
                "a_share": a_share,
                "hk": hk,
                "us": us,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        }


# 全局单例
fund_flow_service = FundFlowService()
