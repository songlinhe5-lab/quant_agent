"""
Data Subservice — Finnhub 数据源 Worker (DIST-22)
==================================================

可选的 Finnhub 数据采集能力，作为第三类辅节点运行。
当 DS_CAPABILITIES 包含 "finnhub" 时启用。

功能:
  - 公司新闻 / 内幕交易 / 财报日历
  - 数据写入 Redis 缓存供主服务读取
"""

from __future__ import annotations

import os
from typing import Optional

import redis.asyncio as aioredis

from backend.core.logger import logger


class FinnhubWorker:
    """Finnhub 数据采集 Worker (DIST-22)"""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._running = False
        self._api_key = os.getenv("FINNHUB_API_KEY", "")

    async def start(self) -> None:
        """启动 Finnhub Worker"""
        if not self._api_key:
            logger.warning("[FinnhubWorker] FINNHUB_API_KEY 未配置，Worker 未启动")
            return
        self._running = True
        logger.info("[FinnhubWorker] Finnhub Worker 已启动 (DIST-22)")

    async def stop(self) -> None:
        """停止 Finnhub Worker"""
        self._running = False
        logger.info("[FinnhubWorker] Finnhub Worker 已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    async def get_company_news(self, symbol: str, days_back: int = 3) -> dict:
        """获取公司新闻"""
        try:
            import httpx

            from_date = None
            to_date = None

            async with httpx.AsyncClient() as client:
                params = {
                    "symbol": symbol,
                    "from": from_date,
                    "to": to_date,
                    "token": self._api_key,
                }
                resp = await client.get(
                    "https://finnhub.io/api/v1/company-news",
                    params=params,
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"status": "success", "data": resp.json()}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Finnhub rate limited", "error_category": "rate_limit"}
                else:
                    return {"status": "error", "message": f"Finnhub HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_insider_transactions(self, symbol: str) -> dict:
        """获取内幕交易"""
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://finnhub.io/api/v1/stock/insider-transactions",
                    params={"symbol": symbol, "token": self._api_key},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"status": "success", "data": resp.json()}
                elif resp.status_code == 429:
                    return {"status": "error", "message": "Finnhub rate limited", "error_category": "rate_limit"}
                else:
                    return {"status": "error", "message": f"Finnhub HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
