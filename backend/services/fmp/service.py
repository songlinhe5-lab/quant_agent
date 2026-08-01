"""
FMP REST 服务（底层数据源，BE-ARCH-04）

仅经 adapter 访问，禁止业务代码直连。
限流接入 rate_limit_registry（与 Finnhub 同模式）：429/403 → on_rate_limit，成功 → on_success。
FMP 免费档约 250 credit/天，单次 quote=1 credit，批量 endpoint 一次消耗数十 credit，
因此本服务只暴露 on-demand 的低频接口，不建议做高频守护。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.services.datasource.registry import rate_limit_registry

_BASE = "https://financialmodelingprep.com/api/v3"


class FMPService:
    """FMP 底层 REST 客户端。"""

    def _key(self) -> str:
        return os.getenv("FMP_API_KEY", "")

    def _th(self):
        return rate_limit_registry.get_throttler("fmp")

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        th = self._th()
        if th.should_throttle():
            return {"status": "error", "message": "rate limited", "error_category": "rate_limit"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{_BASE}/quote/{symbol}", params={"apikey": self._key()})
        if r.status_code == 200:
            th.on_success()
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            th.on_rate_limit()
            return {"status": "error", "message": "FMP 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"FMP HTTP {r.status_code}"}

    async def get_profile(self, symbol: str) -> dict[str, Any]:
        th = self._th()
        if th.should_throttle():
            return {"status": "error", "message": "rate limited", "error_category": "rate_limit"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{_BASE}/profile/{symbol}", params={"apikey": self._key()})
        if r.status_code == 200:
            th.on_success()
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            th.on_rate_limit()
            return {"status": "error", "message": "FMP 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"FMP HTTP {r.status_code}"}

    async def get_income_statement(self, symbol: str, limit: int = 4) -> dict[str, Any]:
        th = self._th()
        if th.should_throttle():
            return {"status": "error", "message": "rate limited", "error_category": "rate_limit"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{_BASE}/income-statement/{symbol}",
                params={"apikey": self._key(), "limit": limit},
            )
        if r.status_code == 200:
            th.on_success()
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            th.on_rate_limit()
            return {"status": "error", "message": "FMP 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"FMP HTTP {r.status_code}"}


fmp_service = FMPService()
