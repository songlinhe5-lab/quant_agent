"""FMP 数据源实现（物理解耦裁剪版，下沉自 backend.services.fmp.service）

按 vibe coding 红线（数据源物理隔离）：
- 只保留与业务无关、纯粹获取 FMP 独立数据源的逻辑 + 其配额保障。
- REST 直连 + 429 限流 + credit 计数/跨日重置（内存态）+ Prometheus 指标。
- 不引入 backend（无 notification_service / 无 watchlist / 无 Redis 写链路保障）。
- 告警出口降级为 metrics + logger，不推送业务通知。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=fmp) 访问本实现。
credit 实时余额经 /metrics (fmp_credit_remaining gauge) 暴露，供 system.py scrape。
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from data_subservice._internal.logger import logger
from data_subservice._internal.metrics import (
    FMP_CREDIT_LIMIT,
    FMP_CREDIT_REMAINING,
    observe_credit_consume,
)

_BASE = "https://financialmodelingprep.com/api/v3"

# ── FMP 每日 credit 预算（免费档约 250/天；env 可覆盖）──
_FMP_DAILY_CREDIT = int(os.getenv("FMP_DAILY_CREDIT", "250"))
# 单次批量 endpoint (income_statement) 消耗 credit，用于预算预估
_FMP_BATCH_CREDIT_COST = int(os.getenv("FMP_BATCH_CREDIT_COST", "30"))

# ── 内存态 credit 配额（进程级；跨日重置靠本地日期戳）──
_credit_spent = 0
_credit_reset_date = time.strftime("%Y-%m-%d")
_request_count = 0
_rate_limit_hits = 0


def _maybe_reset_daily_credit() -> None:
    """跨日自动重置 credit 计数（内存态）。"""
    global _credit_spent, _credit_reset_date
    today = time.strftime("%Y-%m-%d")
    if today != _credit_reset_date:
        _credit_spent = 0
        _credit_reset_date = today
        logger.info("🔄 [FMP] 跨日重置 credit 计数")


def _credit_remaining() -> int:
    _maybe_reset_daily_credit()
    return max(0, _FMP_DAILY_CREDIT - _credit_spent)


def _consume_credit(n: int = 1) -> bool:
    """尝试消耗 n credit；预算耗尽返回 False（调用方应中止）。"""
    if _credit_remaining() < n:
        logger.warning(f"⚠️ [FMP] credit 预算耗尽 ({_credit_remaining()} 剩余)，拒绝请求")
        return False
    global _credit_spent
    _credit_spent += n
    observe_credit_consume(n, _credit_remaining(), _FMP_DAILY_CREDIT)
    return True


class FMPService:
    """FMP 底层 REST 客户端（子服务叶子节点）。

    限流：本地简单令牌判断（429 命中计数）+ Prometheus 暴露；
    不走主服务 rate_limit_registry（子服务无该 registry）。
    """

    def _key(self) -> str:
        return os.getenv("FMP_API_KEY", "")

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        if not _consume_credit(1):
            return {"status": "error", "message": "FMP credit budget exhausted", "error_category": "quota"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{_BASE}/quote/{symbol}", params={"apikey": self._key()})
        return self._parse(r, credit=1)

    async def get_profile(self, symbol: str) -> dict[str, Any]:
        if not _consume_credit(1):
            return {"status": "error", "message": "FMP credit budget exhausted", "error_category": "quota"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{_BASE}/profile/{symbol}", params={"apikey": self._key()})
        return self._parse(r, credit=1)

    async def get_income_statement(self, symbol: str, limit: int = 4) -> dict[str, Any]:
        # 批量 endpoint 单次消耗数十 credit，先按预算预估拦截
        if not _consume_credit(_FMP_BATCH_CREDIT_COST):
            return {"status": "error", "message": "FMP credit budget exhausted", "error_category": "quota"}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(
                f"{_BASE}/income-statement/{symbol}",
                params={"apikey": self._key(), "limit": limit},
            )
        return self._parse(r, credit=_FMP_BATCH_CREDIT_COST)

    def _parse(self, r: httpx.Response, credit: int) -> dict[str, Any]:
        global _request_count, _rate_limit_hits
        _request_count += 1
        if r.status_code == 200:
            return {"status": "success", "data": r.json()}
        if r.status_code == 429:
            _rate_limit_hits += 1
            logger.warning("⚠️ [FMP] 429 rate limited")
            return {"status": "error", "message": "FMP 429 rate limited", "error_category": "rate_limit"}
        logger.error(f"❌ [FMP] HTTP {r.status_code}")
        return {"status": "error", "message": f"FMP HTTP {r.status_code}"}


fmp_service = FMPService()


def credit_snapshot() -> dict[str, Any]:
    """供 /metrics 与 handler 读取的 credit 运行状态快照。"""
    return {
        "daily_limit": _FMP_DAILY_CREDIT,
        "spent": _credit_spent,
        "remaining": _credit_remaining(),
        "reset_date": _credit_reset_date,
        "request_count": _request_count,
        "rate_limit_hits": _rate_limit_hits,
    }
