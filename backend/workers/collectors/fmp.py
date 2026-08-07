"""
FMP 财报批量守护 (COLLECTOR_FMP) · 业务编排层（vibe coding 红线版）

责任边界（数据源物理隔离）：
  - 本文件只保留业务编排：watchlist 热重载 / 盘后调度 / 通知告警。
  - 数据源连接层（FMPService REST + 429 限流 + credit 计数/持久化/跨日重置）
    已整体下沉至 data_subservice（_internal/fmp + fmp_worker.py），
    经 DataSourceRouter HTTP (source=fmp) 调用，主服务不持有 FMP REST 客户端。
  - credit 预算实时余额由子服务持有；主服务经 fetch_fmp("CREDIT") 读取快照做预算决策，
    不重复实现配额计数/持久化（那是数据源配额保障，归子服务）。
  - 主服务 Redis 写链路健康由主服务通用健康检查覆盖，不再挂在 FMP 守护内。

盘后批量：决定"拉哪些标的 / 何时拉"，实际 REST 与 credit 消耗在子服务完成；
拉回的财报经主服务写入 Redis (quant:fmp:{symbol})，供 adapter 当日命中本地缓存。
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone

from backend.core.logger import logger
from backend.core.metrics import (
    FMP_BATCH_DURATION,
    FMP_BATCH_RUNS_TOTAL,
    FMP_LAST_BATCH_TIMESTAMP,
    FMP_SUBSERVICE_UNREACHABLE,
    FMP_SYMBOLS_CACHED_TOTAL,
    FMP_SYMBOLS_FAILED_TOTAL,
    FMP_WATCHLIST_EMPTY,
    FMP_WATCHLIST_FILE_DELETED,
    FMP_WATCHLIST_SIZE,
    FMP_WATCHLIST_SIZE_SHIFT,
)
from backend.core.redis_client import redis_client

# watchlist 热重载状态（进程内缓存 + mtime 跟踪）
_watchlist_cache: list[str] = []
_watchlist_mtimes: dict[str, float] = {}  # 多文件 mtime 快照（watchlist + portfolio 源均纳入热重载）
_watchlist_prev_size: int = -1  # 上一轮标的池大小（突变检测基线，初始 -1 跳过首轮）
_watchlist_lock = threading.Lock()
_watchlist_monitor_stop = threading.Event()

# 主服务经子服务 CREDIT 快照维护的当日预算进度（仅业务观测用，不持久化）
_credit_spent_today: int = 0
_credit_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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


async def _fetch_fmp(action: str, symbol: str = "", limit: int = _BATCH_LIMIT) -> dict:
    """经 DataSourceRouter 调子服务 source=fmp（失败/未启用自动降级本地直连）。"""
    from backend.services.datasource.router import data_source_router

    params = {}
    if symbol:
        params["symbol"] = symbol
    if action == "INCOME_STATEMENT":
        params["limit"] = limit
    return await data_source_router.fetch_fmp(action, **params)


async def _cache_financials(symbol: str) -> int:
    """拉取并缓存单标的财报，返回消耗的 credit 估算（0 表示失败/限流）。

    实际 REST 与 credit 计数在子服务完成；主服务仅消费子服务 CREDIT 快照做进度跟踪。
    """
    inc = await _fetch_fmp("INCOME_STATEMENT", symbol, limit=_BATCH_LIMIT)
    if inc.get("status") != "success":
        logger.warning(f"[FMP Collector] income_statement 失败 {symbol}: {inc.get('message')}")
        FMP_SYMBOLS_FAILED_TOTAL.labels(reason="fetch").inc()
        return 0

    prof = await _fetch_fmp("PROFILE", symbol)
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
        FMP_SYMBOLS_CACHED_TOTAL.inc()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[FMP Collector] Redis 写入失败 {symbol}: {e}")
        FMP_SYMBOLS_FAILED_TOTAL.labels(reason="redis").inc()
        return 0
    # credit 进度跟踪（仅业务观测，真实配额在子服务；子服务 CREDIT 快照覆盖权威值）
    used = _BATCH_LIMIT_CREDIT()
    return used


def _BATCH_LIMIT_CREDIT() -> int:
    """单标的 credit 估算（income_statement + profile 共 2 端点的标准计费）。

    仅用于主服务本地预算进度展示；真实配额以子服务 source=fmp CREDIT 为准。
    """
    return 2


async def _sync_credit_from_subservice() -> dict:
    """从子服务读取 credit 快照（权威），用于预算决策与运行态展示。

    子服务不可达时回退到主服务本地估算（_credit_spent_today），保证守护不空转。
    """
    global _credit_spent_today, _credit_reset_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _credit_reset_date:
        _credit_spent_today = 0
        _credit_reset_date = today
    try:
        snap = await _fetch_fmp("CREDIT")
        if snap.get("status") == "success":
            data = snap.get("data", {})
            _credit_spent_today = data.get("spent", _credit_spent_today)
            _credit_reset_date = data.get("reset_date", _credit_reset_date)
            FMP_SUBSERVICE_UNREACHABLE.set(0)
            return data
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[FMP Collector] 读取子服务 credit 快照失败，回退本地估算: {e}")
    # 取数失败或返回非 success：预算决策已降级为本地估算，置位供告警
    FMP_SUBSERVICE_UNREACHABLE.set(1)
    return {"spent": _credit_spent_today, "remaining": -1, "reset_date": _credit_reset_date}


def _load_watchlist() -> list[str]:
    """解析 FMP 守护独立 watchlist，多源并集（去重保序）：

    源优先级（高优先源的 symbol 不会被低优先源覆盖，而是合并）：
    1. FMP_COLLECTOR_SYMBOLS (env, 逗号分隔) —— 运营显式指定，最高优先
    1.5 PORTFOLIO_SYMBOLS (env) / config/portfolio_symbols.txt (文件) —— 实盘持仓池并集
    2. FMP_COLLECTOR_WATCHLIST (独立文件, 每行一个 symbol) —— 与 FINNHUB_WS_SYMBOLS 解耦
    3. FINNHUB_WS_SYMBOLS (env, 逗号分隔) —— 兼容旧配置（统一行情池回退）

    返回去重后的并集；若所有源皆空，返回 []（由调用方触发空告警，防静默兜底）。
    """
    merged: list[str] = []
    seen: set[str] = set()

    def _add(syms: list[str]) -> None:
        for s in syms:
            s = s.strip().upper()
            if s and s not in seen:
                seen.add(s)
                merged.append(s)

    # 1. 运营显式 env
    env_syms = os.getenv("FMP_COLLECTOR_SYMBOLS", "").strip()
    if env_syms:
        _add([s for s in env_syms.split(",") if s.strip()])

    # 1.5 实盘持仓池（env 优先，其次独立文件）
    pf_env = os.getenv("PORTFOLIO_SYMBOLS", "").strip()
    if pf_env:
        _add([s for s in pf_env.split(",") if s.strip()])
    else:
        pf_path = os.getenv("PORTFOLIO_SYMBOLS_FILE", "config/portfolio_symbols.txt")
        if pf_path and os.path.isfile(pf_path):
            try:
                with open(pf_path, encoding="utf-8") as f:
                    _add([ln for ln in f if ln.strip() and not ln.startswith("#")])
            except OSError as e:
                logger.warning(f"[FMP Collector] portfolio 标的源读取失败 {pf_path}: {e}")

    # 2. 独立 watchlist 文件
    wl_path = os.getenv("FMP_COLLECTOR_WATCHLIST", "config/fmp_watchlist.txt")
    if wl_path and os.path.isfile(wl_path):
        try:
            with open(wl_path, encoding="utf-8") as f:
                _add([ln for ln in f if ln.strip() and not ln.startswith("#")])
        except OSError as e:
            logger.warning(f"[FMP Collector] watchlist 读取失败 {wl_path}: {e}")

    # 3. 兼容旧配置：回退到 Finnhub WS symbols（统一行情池）
    fb = os.getenv("FINNHUB_WS_SYMBOLS", "").strip()
    if fb:
        _add([s for s in fb.split(",") if s.strip()])

    return merged


def collector_runtime() -> dict:
    """对外暴露守护运行态（供 /observability 聚合，避免直接 import 私有全局变量）。

    仅保留业务编排相关运行态；credit 配额权威值在子服务 /metrics，经 fetch_fmp("CREDIT") 读取。
    """
    return {
        "credit_spent_today": _credit_spent_today,
        "credit_reset_date": _credit_reset_date,
        "watchlist_size": len(_watchlist_cache),
        "watchlist_empty_warn": len(_watchlist_cache) == 0,
    }


def _resolve_monitored_paths() -> list[str]:
    """解析所有需要热重载监听的文件路径（watchlist 文件 + portfolio 文件源）。

    仅返回实际存在的文件（env 指定但文件不存在的路径不纳入监听，避免无谓轮询）。
    """
    paths: list[str] = []
    wl_path = os.getenv("FMP_COLLECTOR_WATCHLIST", "config/fmp_watchlist.txt")
    if wl_path and os.path.isfile(wl_path):
        paths.append(wl_path)
    # portfolio 文件源（仅当未用 env 直接指定时才监听文件）
    if not os.getenv("PORTFOLIO_SYMBOLS", "").strip():
        pf_path = os.getenv("PORTFOLIO_SYMBOLS_FILE", "config/portfolio_symbols.txt")
        if pf_path and os.path.isfile(pf_path):
            paths.append(pf_path)
    # 去重保序
    return list(dict.fromkeys(paths))


def _reload_watchlist() -> bool:
    """重新解析 watchlist 并刷新进程内缓存。返回是否有变化。"""
    global _watchlist_cache, _watchlist_mtimes, _watchlist_prev_size
    syms = _load_watchlist()
    with _watchlist_lock:
        if syms == _watchlist_cache:
            return False
        _watchlist_cache = syms
    # 池规模与空池告警位（每次实际变更后刷新，供 Grafana 观测标的池健康）
    FMP_WATCHLIST_SIZE.set(len(syms))
    FMP_WATCHLIST_EMPTY.set(1 if not syms else 0)
    # 刷新所有监听文件的 mtime 快照
    for p in _resolve_monitored_paths():
        try:
            _watchlist_mtimes[p] = os.path.getmtime(p)
        except OSError:
            _watchlist_mtimes[p] = -1.0
    # 突变检测：相对上一轮 size 变化超过 ±50% 即记日志（提示账户调仓异常或文件误删）
    if _watchlist_prev_size >= 0 and _watchlist_prev_size > 0:
        _ratio = abs(len(syms) - _watchlist_prev_size) / _watchlist_prev_size
        if _ratio >= 0.5:
            logger.warning(
                f"[FMP Collector] watchlist 标的池突变 {_watchlist_prev_size} → {len(syms)} "
                f"(±{_ratio:.0%} ≥ 50%)，提示账户调仓异常或文件误删"
            )
            FMP_WATCHLIST_SIZE_SHIFT.inc()
    _watchlist_prev_size = len(syms)
    logger.info(f"[FMP Collector] watchlist 刷新 → {len(syms)} 个标的")
    return True


def _get_watchlist() -> list[str]:
    """读取进程内热重载缓存（无需每次重解析文件）。"""
    with _watchlist_lock:
        return list(_watchlist_cache)


def _watch_watchlist_file() -> None:
    """后台线程：轮询监听文件 mtime，任一变更即热重载（跨平台，避免引入 inotify 依赖）。

    监听范围 = watchlist 文件 + portfolio 文件源（见 _resolve_monitored_paths）。
    账户调仓后更新 portfolio 文件即可被捕获，无需重启守护。
    """
    poll_interval = 5.0
    while not _watchlist_monitor_stop.is_set():
        triggered = False
        # ① 现存文件：mtime 变更 → 重载
        for p in _resolve_monitored_paths():
            try:
                mtime = os.path.getmtime(p)
                if _watchlist_mtimes.get(p, -1.0) != mtime:
                    logger.info(f"[FMP Collector] 检测到 watchlist/portfolio 文件变更: {p}")
                    _reload_watchlist()
                    triggered = True
                    break  # 一次重载已合并所有源，无需逐个重复触发
            except OSError:
                pass
        # ② 已删除检测：mtime 字典含该 key 但文件已消失 → 防止 stale 池残留
        if not triggered:
            for p in list(_watchlist_mtimes.keys()):
                if p not in _resolve_monitored_paths() and not os.path.exists(p):
                    logger.warning(
                        f"[FMP Collector] 检测到 watchlist/portfolio 文件被删除: {p}，"
                        f"重置该源并触发重载（防 stale 池残留）"
                    )
                    del _watchlist_mtimes[p]
                    FMP_WATCHLIST_FILE_DELETED.inc()
                    _reload_watchlist()
                    triggered = True
                    break
        _watchlist_monitor_stop.wait(poll_interval)


async def _batch_run() -> None:
    global _credit_spent_today
    _batch_started = time.monotonic()
    symbols = _get_watchlist()
    if not symbols:
        logger.error(
            "[FMP Collector] watchlist 为空（FMP_COLLECTOR_SYMBOLS/PORTFOLIO_SYMBOLS/"
            "WATCHLIST/FINNHUB_WS_SYMBOLS 均未配置任何源），守护静默兜底未拉取任何财报！"
        )
        FMP_BATCH_RUNS_TOTAL.labels(result="skipped_empty_watchlist").inc()
        return

    # 预算决策：以子服务 credit 快照为权威（不可达则回退本地估算）
    snap = await _sync_credit_from_subservice()
    daily_budget = int(os.getenv("FMP_COLLECTOR_DAILY_CREDIT", "200"))  # 免费档 250 上限
    remaining = snap.get("remaining", -1)
    budget_exhausted = remaining >= 0 and remaining <= 0

    if budget_exhausted:
        logger.warning(f"[FMP Collector] 子服务 credit 预算已耗尽（remaining={remaining}），停止本轮拉取")
        FMP_BATCH_RUNS_TOTAL.labels(result="skipped_budget").inc()
        return

    hit_market_hours = False
    for sym in symbols:
        if not _in_after_hours_utc():
            logger.info("[FMP Collector] 当前为盘中时段，推迟至盘后执行")
            hit_market_hours = True
            break
        used = await _cache_financials(sym)
        if used > 0:
            _credit_spent_today += used
        else:
            # 失败/限流：跳过该标的，避免空耗后续
            continue
        # 批次间留白，避免突发打满限流
        await asyncio.sleep(1.0)

    # 盘中早退与正常跑完分开计数：前者不代表业务产出，勿混入 completed 稀释成功率
    FMP_BATCH_RUNS_TOTAL.labels(result="skipped_market_hours" if hit_market_hours else "completed").inc()
    FMP_BATCH_DURATION.observe(time.monotonic() - _batch_started)
    FMP_LAST_BATCH_TIMESTAMP.set(time.time())
    logger.info(f"[FMP Collector] 本轮盘后批量完成，当日累计 credit≈{_credit_spent_today}/{daily_budget}")


async def fmp_collector_daemon() -> None:
    """盘后批量守护主循环：每 6 小时触发一次（天然只会在盘后窗口实际拉取）。

    启动即加载 watchlist 并开启后台热重载监控线程（文件变更即时刷新标的池）。
    credit 配额保障与 Redis 写链路自愈已在子服务 / 主服务通用健康检查完成，本守护不再内嵌。
    """
    logger.info("[FMP Collector] 守护进程启动 (盘后批量拉财报 → Redis, 数据源经子服务)")
    _reload_watchlist()  # 首启加载 watchlist
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
