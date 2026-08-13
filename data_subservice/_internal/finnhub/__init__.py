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


def _to_finnhub_symbol(ticker: str) -> str:
    """将业务侧 ticker 归一化为 Finnhub 认可的 symbol 格式。

    Finnhub 港股必须用 ``HK:XXXX`` 交易所前缀格式；``XXXX.HK`` / ``HK.XXXX`` 会被
    403 拒绝。美股 ``US.AAPL`` 去掉交易所前缀转 ``AAPL``。A 股原样透传
    （Finnhub 对 A 股无数据，由 facade 的报价市场路由将 A 股降级到 AKShare/Tushare）。
    """
    s = (ticker or "").strip().upper()
    if not s:
        return s
    # 已是 Finnhub 前缀格式 (HK:XXXX) 直接透传
    if ":" in s:
        return s
    # 港股：HK.00700 / 00700.HK / 0700.HK -> HK:0700 (Finnhub 用 4 位港股代码)
    if s.startswith("HK."):
        code = s[3:].zfill(4) if s[3:].isdigit() else s[3:]
        return f"HK:{code}"
    if s.endswith(".HK"):
        code = s[:-3].zfill(4) if s[:-3].isdigit() else s[:-3]
        return f"HK:{code}"
    # 美股：US.AAPL -> AAPL (Finnhub 美股无交易所前缀)
    if s.startswith("US."):
        return s[3:]
    return s


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
        sym = _to_finnhub_symbol(ticker)
        resp = await self._get("/quote", {"symbol": sym})
        # 免费版港股/未覆盖市场：HTTP 200 但返回全 0 占位 (c=0,h=0,l=0,pc=0,t=0)。
        # 必须拦截，否则行情面板会把标的显示成 $0.00，比数据缺失更危险（零幻觉红线）。
        if resp.get("status") == "success":
            d = resp.get("data") or {}
            if isinstance(d, dict) and d.get("c") in (0, 0.0) and d.get("pc") in (0, 0.0) and d.get("t") in (0, 0.0):
                return {
                    "status": "error",
                    "message": f"Finnhub 免费版不支持 {sym} 实时报价（返回全 0）",
                    "error_category": "unsupported_market",
                }
        return resp

    async def get_company_news(self, ticker: str, days_back: int = 3) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow()
        frm = to - timedelta(days=days_back)
        fmt = "%Y-%m-%d"
        return await self._get(
            "/company-news",
            {"symbol": _to_finnhub_symbol(ticker), "from": frm.strftime(fmt), "to": to.strftime(fmt)},
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
        return await self._get("/stock/insider-transactions", {"symbol": _to_finnhub_symbol(ticker)})

    async def get_dividend_calendar(self, symbol: str | None = None) -> dict[str, Any]:
        """分红日历 (BE-ARCH-07e: 自 calendars 路由下沉)。可选按 symbol 过滤。"""
        params = {"symbol": symbol} if symbol else {}
        return await self._get("/calendar/dividend", params)

    async def get_ipo_calendar(self) -> dict[str, Any]:
        """IPO 日历 (BE-ARCH-07e: 自 calendars 路由下沉)。"""
        return await self._get("/calendar/ipo", {})

    async def get_stock_history(self, ticker: str, days_back: int = 365) -> dict[str, Any]:
        from datetime import datetime, timedelta

        to = datetime.utcnow()
        frm = to - timedelta(days=days_back)
        return await self._get(
            "/stock/candle",
            {
                "symbol": _to_finnhub_symbol(ticker),
                "resolution": "D",
                "from": int(frm.timestamp()),
                "to": int(to.timestamp()),
            },
        )


finnhub_service = FinnhubService()
