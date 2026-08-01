"""
FMP 财报批量守护 (COLLECTOR_FMP)

盘后批量拉取标的的 income_statement / profile，写 Redis (quant:fmp:{symbol})，
TTL 1 天，供 adapter 当日按需命中本地缓存、减少重复 REST 调用、控制 credit 消耗。

红线：
  - 仅 master 节点运行（slave 不启 daemon）。
  - 严格受 rate_limit_registry 的 fmp throttler 限流 + 每日 credit 预算双重约束。
  - 单次批量 endpoint 消耗数十 credit，故 limit 取小值 (默认 4 季)，绝不拉全量。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.services.datasource.registry import rate_limit_registry
from backend.services.fmp.service import fmp_service

# watchlist 热重载状态（进程内缓存 + mtime 跟踪）
_watchlist_cache: list[str] = []
_watchlist_mtime: float = -1.0
_watchlist_lock = threading.Lock()
_watchlist_monitor_stop = threading.Event()

_FMP_REDIS_TTL = 24 * 3600  # 财报缓存 1 天
_BATCH_LIMIT = 4  # 每标的拉取的季度数（控制 credit：income_statement 1 call = 数 credit）
# 盘后窗口（UTC）：美东 ET=UTC-4(夏令)/-5(冬令)。盘后≈收盘 16:00 ET 后至盘前 09:30 ET。
# UTC 覆盖：夏令 20:00–次日 13:30；冬令 21:00–次日 14:30。取宽松并集 [20, 14) UTC。
_MARKET_OPEN_UTC_START = 14  # 14:00 UTC 后视为盘后开始（保守覆盖冬令）
_MARKET_OPEN_UTC_END = 20  # 20:00 UTC 前视为盘前/盘后（即 20:00–24:00 算盘中，避开）


def _in_after_hours_utc() -> bool:
    """粗略盘后判定（按 UTC 小时，避免引入 pytz 等重依赖）。"""
    hour = datetime.now(timezone.utc).hour
    # 盘中美东时段映射到 UTC 约 13:30–20:00，避开它；其余视为盘后/盘前可跑
    return not (_MARKET_OPEN_UTC_END <= hour < 24 and hour >= 13)


async def _cache_financials(symbol: str) -> int:
    """拉取并缓存单标的财报，返回消耗的 credit 估算（0 表示失败/限流）。"""
    th = rate_limit_registry.get_throttler("fmp")
    if th.should_throttle():
        logger.warning(f"[FMP Collector] throttler 触发，跳过 {symbol}")
        return 0

    inc = await fmp_service.get_income_statement(symbol, limit=_BATCH_LIMIT)
    if inc.get("status") != "success":
        logger.warning(f"[FMP Collector] income_statement 失败 {symbol}: {inc.get('message')}")
        return 0

    prof = await fmp_service.get_profile(symbol)
    profile_ok = prof.get("status") == "success"

    payload = {
        "symbol": symbol.upper(),
        "income_statement": inc.get("data"),
        "profile": prof.get("data") if profile_ok else None,
        "cached_at": int(time.time()),
    }
    key = f"quant:fmp:{symbol.upper()}"
    try:
        await redis_client.set(key, json.dumps(payload, default=str), ex=_FMP_REDIS_TTL)
        logger.info(f"[FMP Collector] 已缓存 {symbol} → {key}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[FMP Collector] Redis 写入失败 {symbol}: {e}")
        return 0
    # 估算 credit：income_statement(约2) + profile(约2)
    used = 4
    # 累计 credit 消耗（与每日预算对账，Prometheus 可查）
    try:
        from backend.core.metrics import FMP_CREDIT_SPENT_TOTAL

        FMP_CREDIT_SPENT_TOTAL.inc(used)
    except Exception:  # noqa: BLE001
        pass
    return used


def _load_watchlist() -> list[str]:
    """解析 FMP 守护独立 watchlist，三级回退：

    1. FMP_COLLECTOR_SYMBOLS (env, 逗号分隔) —— 最高优先
    2. FMP_COLLECTOR_WATCHLIST (独立文件, 每行一个 symbol) —— 与 FINNHUB_WS_SYMBOLS 解耦
    3. FINNHUB_WS_SYMBOLS (env, 逗号分隔) —— 兼容旧配置
    """
    env_syms = os.getenv("FMP_COLLECTOR_SYMBOLS", "").strip()
    if env_syms:
        return [s.strip().upper() for s in env_syms.split(",") if s.strip()]

    wl_path = os.getenv("FMP_COLLECTOR_WATCHLIST", "config/fmp_watchlist.txt")
    if wl_path and os.path.isfile(wl_path):
        try:
            with open(wl_path, encoding="utf-8") as f:
                syms = [ln.strip().upper() for ln in f if ln.strip() and not ln.startswith("#")]
            if syms:
                return syms
        except OSError as e:
            logger.warning(f"[FMP Collector] watchlist 读取失败 {wl_path}: {e}")

    # 兼容旧配置：回退到 Finnhub WS symbols
    fb = os.getenv("FINNHUB_WS_SYMBOLS", "").strip()
    if fb:
        return [s.strip().upper() for s in fb.split(",") if s.strip()]
    return []


def _resolve_watchlist_path() -> str:
    """解析当前 watchlist 文件路径（env 优先；否则默认文件）。"""
    wl_path = os.getenv("FMP_COLLECTOR_WATCHLIST", "config/fmp_watchlist.txt")
    return wl_path if wl_path and os.path.isfile(wl_path) else ""


def _reload_watchlist() -> bool:
    """重新解析 watchlist 并刷新进程内缓存。返回是否有变化。"""
    global _watchlist_cache, _watchlist_mtime
    syms = _load_watchlist()
    with _watchlist_lock:
        if syms == _watchlist_cache:
            return False
        _watchlist_cache = syms
    wl_path = _resolve_watchlist_path()
    if wl_path:
        try:
            _watchlist_mtime = os.path.getmtime(wl_path)
        except OSError:
            _watchlist_mtime = -1.0
    logger.info(f"[FMP Collector] watchlist 刷新 → {len(syms)} 个标的")
    return True


def _get_watchlist() -> list[str]:
    """读取进程内热重载缓存（无需每次重解析文件）。"""
    with _watchlist_lock:
        return list(_watchlist_cache)


def _watch_watchlist_file() -> None:
    """后台线程：轮询 watchlist 文件 mtime，变更即热重载（跨平台，避免引入 inotify 依赖）。"""
    poll_interval = 5.0
    while not _watchlist_monitor_stop.is_set():
        wl_path = _resolve_watchlist_path()
        if wl_path:
            try:
                mtime = os.path.getmtime(wl_path)
                if mtime != _watchlist_mtime:
                    logger.info(f"[FMP Collector] 检测到 watchlist 文件变更: {wl_path}")
                    _reload_watchlist()
            except OSError:
                pass
        _watchlist_monitor_stop.wait(poll_interval)


async def _batch_run() -> None:
    symbols = _get_watchlist()
    if not symbols:
        logger.info("[FMP Collector] 未配置 watchlist（FMP_COLLECTOR_SYMBOLS/WATCHLIST/FINNHUB_WS_SYMBOLS 均空），跳过")
        return

    daily_budget = int(os.getenv("FMP_COLLECTOR_DAILY_CREDIT", "200"))  # 免费档 250 上限
    spent = 0
    for sym in symbols:
        if spent >= daily_budget:
            logger.warning(f"[FMP Collector] 触及每日 credit 预算 {daily_budget}，停止剩余拉取")
            break
        if not _in_after_hours_utc():
            logger.info("[FMP Collector] 当前为盘中时段，推迟至盘后执行")
            break
        used = await _cache_financials(sym)
        spent += used
        # 批次间留白，避免突发打满限流
        await asyncio.sleep(1.0)
    logger.info(f"[FMP Collector] 本轮盘后批量完成，消耗 credit≈{spent}")


async def fmp_collector_daemon() -> None:
    """盘后批量守护主循环：每 6 小时触发一次（天然只会在盘后窗口实际拉取）。

    启动即加载 watchlist 并开启后台热重载监控线程（文件变更即时刷新标的池）。
    """
    logger.info("[FMP Collector] 守护进程启动 (盘后批量拉财报 → Redis)")
    _reload_watchlist()  # 首启加载
    monitor = threading.Thread(target=_watch_watchlist_file, name="fmp-watchlist-mon", daemon=True)
    monitor.start()
    try:
        while True:
            try:
                await _batch_run()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[FMP Collector] 批次异常: {e}")
            # 每 6h 一轮；盘内窗口 _batch_run 自行早退，不空转消耗 credit
            await asyncio.sleep(6 * 3600)
    finally:
        _watchlist_monitor_stop.set()


async def start() -> list:
    """采集器工厂入口（BE-ARCH-03）。仅 master 启 daemon。"""
    node_type = os.getenv("NODE_TYPE", "master")
    if node_type != "master":
        logger.info("  [fmp] slave mode: 不启批量守护")
        return []
    if not os.getenv("FMP_API_KEY"):
        logger.warning("  [fmp] 未配置 FMP_API_KEY，跳过守护")
        return []
    return [fmp_collector_daemon()]
