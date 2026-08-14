"""行情生产者采集器工厂 (QUOTE_PUBLISHER) · 业务编排层。

职责：将 QuotePublisher.run_daemon 注册为 worker 常驻后台任务，
周期性轮询标的的报价 + Level 2 盘口，经 Protobuf 编码后 publish 到
Redis ``quant:quotes:stream``，前端 WebSocket (use-market-data.ts) 订阅后
dispatch ``market_tick`` 事件 → OrderBookWebGL 渲染 Level 2。

此前该 daemon 仅挂在 quote_publisher.py 的 ``__main__`` 里，未被任何常驻
worker 启动，导致盘口数据永不推送、前端 Level 2 长期空白。本工厂将其纳入
collector 注册表 (BE-ARCH-03)，随 start_collector_daemons 自动拉起。

盘口推送标的池 = 前端实际订阅标的 (Redis ``quant:ws:subscribed_tickers``，
由 ConnectionManager.subscribe/unsubscribe 动态维护) ∪ 下方兜底常驻池。
→ 保证盘口推送与前端自选列表动态一致（PROD-04）。本工厂加载的仅为兜底常驻池：

  1. QUOTE_PUBLISHER_SYMBOLS (env, 逗号分隔) —— 运营显式指定，最高优先
  2. config/quote_watchlist.txt (每行一个 symbol) —— 与 FMP watchlist 解耦
  3. 回退默认池 ["US.AAPL","HK.00700","US.TSLA"]
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Coroutine
from typing import Any

logger = __import__("logging").getLogger(__name__)

_DEFAULT_SYMBOLS = ["US.AAPL", "HK.00700", "US.TSLA"]


def _load_symbols() -> list[str]:
    """解析盘口推送标的池（多源并集，去重保序）。"""
    seen: set[str] = set()
    out: list[str] = []

    def _add(items: list[str]) -> None:
        for s in items:
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)

    # 1. env 显式指定
    env = os.getenv("QUOTE_PUBLISHER_SYMBOLS", "").strip()
    if env:
        _add([s for s in env.split(",")])

    # 2. 独立 watchlist 文件
    wl_path = os.getenv("QUOTE_PUBLISHER_WATCHLIST", "config/quote_watchlist.txt")
    if wl_path and os.path.isfile(wl_path):
        try:
            with open(wl_path, encoding="utf-8") as f:
                _add([ln for ln in f if ln.strip() and not ln.startswith("#")])
        except OSError as e:  # pragma: no cover - defensive
            logger.warning("[QUOTE_PUBLISHER] watchlist 读取失败 %s: %s", wl_path, e)

    # 3. 回退默认池
    if not out:
        _add(_DEFAULT_SYMBOLS)

    return out


async def quote_publisher_daemon() -> None:
    """常驻守护：轮询盘口 + 报价并推送到 Redis 总线。"""
    from backend.workers.quote_publisher import QuotePublisher

    symbols = _load_symbols()
    logger.info("[QUOTE_PUBLISHER] 启动行情生产者 daemon，关注标的: %s", symbols)
    pub = QuotePublisher()
    # interval=1.5s 与历史 __main__ 行为保持一致；盘口为高频场景可下调
    await pub.run_daemon(symbols, interval=1.5)


async def start() -> list[Coroutine[Any, Any, Any] | Awaitable[Any]]:
    return [quote_publisher_daemon()]
