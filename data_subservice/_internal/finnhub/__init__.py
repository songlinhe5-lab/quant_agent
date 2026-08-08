"""Finnhub 数据源实现（物理解耦裁剪版，下沉自 backend.services.finnhub.service）

按 vibe coding 红线（数据源物理隔离）：
- 只保留与业务无关、纯粹获取 Finnhub 独立数据源的 REST 逻辑。
- REST 直连 + 429 限流计数 + Prometheus 指标。
- 不引入 backend（无 notification_service / 无 WS 订阅 / 无 Redis 写链路）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=finnhub) 访问本实现。
WS tick 订阅已从主服务移除（见 AGENTS.md §6 沙箱约束），quote 走 REST 快照。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from data_subservice._internal.logger import logger

_BASE = "https://finnhub.io/api/v1"


class FinnhubService:
    """Finnhub 底层 REST 客户端（子服务叶子节点）。"""

    def _key(self) -> str:
        return os.getenv("FINNHUB_API_KEY", "")

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._key():
            return {"status": "error", "message": "FINNHUB_API_KEY 未配置"}
        params = {k: v for k, v in params.items() if v is not None}
        params["token"] = self._key()
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.get(f"{_BASE}{path}", params=params)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [Finnhub] 请求失败 {path}: {e}")
            return {"status": "error", "message": f"Finnhub request failed: {e}"}
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            return {"status": "error", "message": "Finnhub 429 rate limited", "error_category": "rate_limit"}
        if r.status_code in (401, 403):
            return {"status": "error", "message": "Finnhub 401/403 IP/Key blocked", "error_category": "ip_blocked"}
        return {"status": "error", "message": f"Finnhub HTTP {r.status_code}"}

    async def get_quote(self, ticker: str) -> dict[str, Any]:
        return await self._get("/quote", {"symbol": ticker})

    async def get_company_news(self, ticker: str, days_back: int = 3) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow()
        frm = to - timedelta(days=days_back)
        fmt = "%Y-%m-%d"
        return await self._get(
            "/company-news",
            {"symbol": ticker, "from": frm.strftime(fmt), "to": to.strftime(fmt)},
        )

    async def get_market_news(self, category: str = "general") -> dict[str, Any]:
        return await self._get("/news", {"category": category})

    async def get_earnings_calendar(self, days_ahead: int = 7, days_back: int = 0) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow() + timedelta(days=days_ahead)
        frm = datetime.utcnow() - timedelta(days=days_back)
        fmt = "%Y-%m-%d"
        return await self._get("/calendar/earnings", {"from": frm.strftime(fmt), "to": to.strftime(fmt)})

    async def get_economic_calendar(self, days_ahead: int = 7, days_back: int = 0) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow() + timedelta(days=days_ahead)
        frm = datetime.utcnow() - timedelta(days=days_back)
        fmt = "%Y-%m-%d"
        return await self._get("/calendar/economic", {"from": frm.strftime(fmt), "to": to.strftime(fmt)})

    async def get_insider_transactions(self, ticker: str, limit: int = 30) -> dict[str, Any]:
        return await self._get("/stock/insider-transactions", {"symbol": ticker})

    async def get_stock_history(self, ticker: str, days_back: int = 365) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow()
        frm = to - timedelta(days=days_back)
        return await self._get(
            "/stock/candle",
            {
                "symbol": ticker,
                "resolution": "D",
                "from": int(frm.timestamp()),
                "to": int(to.timestamp()),
            },
        )


finnhub_service = FinnhubService()
