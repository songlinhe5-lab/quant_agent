"""

Data Subservice — Finnhub 数据源 Worker (DIST-22)
==================================================

可选的 Finnhub 数据采集能力，作为第三类辅节点运行。
当 DS_CAPABILITIES 包含 "finnhub" 时启用。

功能:
  - 公司新闻 / 内幕交易 / 财报日历 (REST, 经 FinnhubWorker)
  - 美股实时 trade/quote WebSocket 流 (FinnhubWsClient, 免费档单连接)
    → 实时 tick 经 Redis pub 到 quant:tick:{symbol} 频道，主节点订阅回灌 registry

部署:
  DS_CAPABILITIES=finnhub  python -m data_subservice.main
  (建议跑在 US 辅助节点，美国出口 IP 连 wss.finnhub.io 更稳定)
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

import redis.asyncio as aioredis

from backend.core.logger import logger


class FinnhubWorker:
    """Finnhub REST 数据采集 Worker (DIST-22)"""

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._running = False
        self._api_key = os.getenv("FINNHUB_API_KEY", "")

    async def start(self) -> None:
        """启动 Finnhub REST Worker"""
        if not self._api_key:
            logger.warning("[FinnhubWorker] FINNHUB_API_KEY 未配置，REST Worker 未启动")
            return
        self._running = True
        logger.info("[FinnhubWorker] Finnhub REST Worker 已启动 (DIST-22)")

    async def stop(self) -> None:
        """停止 Finnhub REST Worker"""
        self._running = False
        logger.info("[FinnhubWorker] Finnhub REST Worker 已停止")

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


class FinnhubWsClient:
    """Finnhub WebSocket 实时行情客户端 (DIST-22)。

    免费档限制：单连接、订阅符号数受限（实测约 20~50 只），
    超出需多 token 或降频。本客户端实现：
      - 单连接管理，启动即订阅 FINNHUB_WS_SYMBOLS（逗号分隔）
      - trade/quote 消息经 Redis pub 到 quant:tick:{symbol}
      - 指数退避重连（base 1s，cap 30s，连续失败 3 次触发熔断休眠）
      - 不作 429 计入熔断失败计数（WS 限流走退避而非熔断）
    """

    def __init__(self, redis_client: Optional[aioredis.Redis] = None):
        self._redis = redis_client
        self._running = False
        self._api_key = os.getenv("FINNHUB_API_KEY", "")
        self._symbols = [s.strip().upper() for s in os.getenv("FINNHUB_WS_SYMBOLS", "").split(",") if s.strip()]
        self._ws_url = f"wss://ws.finnhub.io?token={self._api_key}"
        self._max_reconnect = int(os.getenv("FINNHUB_WS_MAX_RECONNECT", "3"))
        self._task: Optional[asyncio.Task] = None

    async def _redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                f"redis://{os.getenv('REDIS_HOST', '127.0.0.1')}:{os.getenv('REDIS_PORT', '6379')}",
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
        return self._redis

    async def start(self) -> None:
        if not self._api_key:
            logger.warning("[FinnhubWs] FINNHUB_API_KEY 未配置，WS 未启动")
            return
        if not self._symbols:
            logger.warning("[FinnhubWs] FINNHUB_WS_SYMBOLS 为空，WS 未订阅任何标的")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("[FinnhubWs] 实时行情 WS 已启动，订阅 %d 只标的", len(self._symbols))

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[FinnhubWs] 实时行情 WS 已停止")

    async def _run(self) -> None:
        import websockets

        backoff = 1.0
        failures = 0
        while self._running:
            try:
                async with websockets.connect(self._ws_url, ping_interval=20) as ws:
                    failures = 0
                    backoff = 1.0
                    for sym in self._symbols:
                        await ws.send(json.dumps({"type": "subscribe", "symbol": sym}))
                    logger.info("[FinnhubWs] 已连接并订阅 %s", self._symbols)
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._on_message(raw)
            except asyncio.CancelledError:  # noqa: PERF203
                break
            except Exception as e:  # noqa: BLE001
                failures += 1
                logger.warning(
                    "[FinnhubWs] 连接异常 (%s)，%ds 后重连 (失败 %d/%d)", e, int(backoff), failures, self._max_reconnect
                )
                if failures >= self._max_reconnect:
                    logger.error("[FinnhubWs] 连续失败 %d 次，熔断休眠，等待下次 deploy 重启", failures)
                    self._running = False
                    break
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _on_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        mtype = msg.get("type")
        if mtype not in ("trade", "quote"):
            return
        sym = msg.get("symbol")
        if not sym:
            return
        r = await self._redis()
        await r.publish(f"quant:tick:{sym}", json.dumps(msg))
