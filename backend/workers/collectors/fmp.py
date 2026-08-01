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

# 每日 credit 预算计数器（按 UTC 日期重置，持久化到 Redis 避免进程重启丢进度）
_credit_spent_today: int = 0
_credit_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Redis 持久化连续失败计数（达阈值升 P1 告警，避免静默丢进度）
_persist_fails: int = 0
_persist_fail_alerted: bool = False  # 已告警标记，避免每轮刷屏
_collector_paused: bool = False  # 持久化连续失败达阈值 → 暂停守护，Redis 恢复后自愈
_PERSIST_FAIL_THRESHOLD: int = 5

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
    global _credit_spent_today
    _credit_spent_today += used
    await _persist_credit()
    # 累计 credit 消耗（与每日预算对账，Prometheus 可查）
    try:
        from backend.core.metrics import FMP_CREDIT_SPENT_TOTAL

        FMP_CREDIT_SPENT_TOTAL.inc(used)
    except Exception:  # noqa: BLE001
        pass
    return used


def _credit_redis_key(date: str) -> str:
    return f"quant:fmp:credit_spent:{date}"


async def _persist_credit() -> bool:
    """将当日 credit 消耗持久化到 Redis（ex=25h 自然过期，进程重启不丢进度）。

    连续写入失败达 _PERSIST_FAIL_THRESHOLD 次 → 升 P1 告警并暂停守护；
    恢复成功时清零计数/标记并解除暂停（自愈）。
    返回 True=写入成功，False=失败。
    """
    global _persist_fails, _persist_fail_alerted, _collector_paused
    try:
        await redis_client.set(
            _credit_redis_key(_credit_reset_date),
            str(_credit_spent_today),
            ex=25 * 3600,
        )
        # 恢复成功 → 清零失败计数与告警标记，解除暂停（自愈）
        if _persist_fails > 0 or _collector_paused:
            logger.info(
                f"[FMP Collector] Redis 持久化恢复，连续失败计数清零"
                f"（此前 {_persist_fails} 次，paused={_collector_paused}）→ 守护自愈重启"
            )
        _persist_fails = 0
        _persist_fail_alerted = False
        was_paused = _collector_paused
        _collector_paused = False
        try:
            from backend.core.metrics import FMP_COLLECTOR_PAUSED, FMP_PERSIST_FAILS

            FMP_COLLECTOR_PAUSED.set(0)
            FMP_PERSIST_FAILS.set(0)
        except Exception:  # noqa: BLE001
            pass
        if was_paused:
            try:
                from backend.core.alert_models import NotificationPriority
                from backend.services.alert.notification import notification_service

                await notification_service.send_alert(
                    message="[FMP Collector] Redis 已恢复，守护自愈重启，credit 进度持久化恢复正常",
                    priority=NotificationPriority.P2,
                    source="fmp-collector",
                )
            except Exception:  # noqa: BLE001
                pass
        return True
    except Exception as e:  # noqa: BLE001
        _persist_fails += 1
        logger.warning(f"[FMP Collector] credit 持久化失败 ({_persist_fails}/{_PERSIST_FAIL_THRESHOLD}): {e}")
        try:
            from backend.core.metrics import FMP_PERSIST_FAILS

            FMP_PERSIST_FAILS.set(_persist_fails)  # 实时暴露连续失败数（Grafana 趋势）
        except Exception:  # noqa: BLE001
            pass
        if _persist_fails >= _PERSIST_FAIL_THRESHOLD:
            if not _persist_fail_alerted:
                _persist_fail_alerted = True
                _collector_paused = True
                try:
                    from backend.core.metrics import FMP_COLLECTOR_PAUSED

                    FMP_COLLECTOR_PAUSED.set(1)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from backend.core.alert_models import NotificationPriority
                    from backend.services.alert.notification import notification_service

                    await notification_service.send_alert(
                        message=(
                            f"[FMP Collector] Redis 持久化连续 {_persist_fails} 次失败，"
                            f"守护已暂停防丢失，待 Redis 恢复后自愈（P1）"
                        ),
                        priority=NotificationPriority.P1,
                        source="fmp-collector",
                    )
                except Exception as alert_e:  # noqa: BLE001
                    logger.error(f"[FMP Collector] P1 告警发送失败: {alert_e}")
        return False


async def _self_heal_loop() -> None:
    """独立自愈短轮询：守护暂停态下尝试 Redis 探测写，成功即自愈重启。

    指数退避避免 Redis 长断期间空转探测写：首探 30s，失败后按 2^n 退避，
    上限 5min；一旦探测成功自愈，退避立即归零。与主批量循环（6h 一轮）解耦。
    """
    base = 30.0
    cap = 300.0
    backoff = base
    while True:
        if _collector_paused:
            try:
                healed = await _persist_credit()  # 成功 → 内部解除 _collector_paused
                if healed:
                    backoff = base  # 自愈成功，退避归零
                else:
                    backoff = min(backoff * 2, cap)  # 仍失败 → 指数退避
            except Exception:  # noqa: BLE001
                backoff = min(backoff * 2, cap)
        else:
            backoff = base  # 未暂停，保持基线，零额外写压力
        await asyncio.sleep(backoff)


async def _restore_credit() -> None:
    """进程启动/跨日时从 Redis 恢复当日 credit 进度（防重启清零）。"""
    global _credit_spent_today, _credit_reset_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _credit_reset_date = today
    try:
        raw = await redis_client.get(_credit_redis_key(today))
        if raw is not None:
            _credit_spent_today = int(raw)
            logger.info(f"[FMP Collector] 从 Redis 恢复当日 credit 进度: {_credit_spent_today} ({today})")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[FMP Collector] credit 恢复失败: {e}")


async def _maybe_reset_daily_credit() -> None:
    """每日 00:00 UTC 重置 credit 预算计数器（进程内 + Redis + Prometheus），避免跨日累计误导。"""
    global _credit_spent_today, _credit_reset_date, _persist_fails, _persist_fail_alerted
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _credit_reset_date:
        logger.info(
            f"[FMP Collector] 跨日重置 credit 计数器 {_credit_reset_date} → {today} (昨日累计 {_credit_spent_today})"
        )
        _credit_spent_today = 0
        _credit_reset_date = today
        _persist_fails = 0
        _persist_fail_alerted = False
        await _persist_credit()  # 写新日期 key（旧 key 25h 后自然过期）
        try:
            from backend.core.metrics import FMP_CREDIT_SPENT_TOTAL

            FMP_CREDIT_SPENT_TOTAL.clear()  # Counter 清零，重新开始当日累计
        except Exception:  # noqa: BLE001
            pass


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


def collector_runtime() -> dict:
    """对外暴露守护运行态（供 /observability 聚合，避免直接 import 私有全局变量）。"""
    return {
        "paused": _collector_paused,
        "persist_fails": _persist_fails,
        "persist_fail_threshold": _PERSIST_FAIL_THRESHOLD,
        "credit_spent_today": _credit_spent_today,
        "credit_reset_date": _credit_reset_date,
        "watchlist_size": len(_watchlist_cache),
    }


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

    await _maybe_reset_daily_credit()

    daily_budget = int(os.getenv("FMP_COLLECTOR_DAILY_CREDIT", "200"))  # 免费档 250 上限
    for sym in symbols:
        if _credit_spent_today >= daily_budget:
            logger.warning(
                f"[FMP Collector] 触及每日 credit 预算 {daily_budget}（已用 {_credit_spent_today}），停止剩余拉取"
            )
            break
        if not _in_after_hours_utc():
            logger.info("[FMP Collector] 当前为盘中时段，推迟至盘后执行")
            break
        await _cache_financials(sym)
        # 批次间留白，避免突发打满限流
        await asyncio.sleep(1.0)
    logger.info(f"[FMP Collector] 本轮盘后批量完成，当日累计 credit≈{_credit_spent_today}/{daily_budget}")


async def fmp_collector_daemon() -> None:
    """盘后批量守护主循环：每 6 小时触发一次（天然只会在盘后窗口实际拉取）。

    启动即加载 watchlist 并开启后台热重载监控线程（文件变更即时刷新标的池）。
    独立 30s 自愈短轮询随守护一并启动，缩短 Redis 恢复后的自愈延迟。
    """
    logger.info("[FMP Collector] 守护进程启动 (盘后批量拉财报 → Redis)")
    await _restore_credit()  # 先恢复当日 credit 进度（防重启清零）
    _reload_watchlist()  # 首启加载 watchlist
    try:
        from backend.core.metrics import FMP_COLLECTOR_PAUSED

        FMP_COLLECTOR_PAUSED.set(0)  # 启动基线：正常态
    except Exception:  # noqa: BLE001
        pass
    monitor = threading.Thread(target=_watch_watchlist_file, name="fmp-watchlist-mon", daemon=True)
    monitor.start()
    self_heal = asyncio.create_task(_self_heal_loop(), name="fmp-self-heal")
    try:
        while True:
            if _collector_paused:
                logger.warning("[FMP Collector] 守护处于暂停态（Redis 故障），跳过批量，30s 自愈轮询待恢复")
                await asyncio.sleep(6 * 3600)
                continue
            try:
                await _batch_run()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[FMP Collector] 批次异常: {e}")
            # 每 6h 一轮；盘内窗口 _batch_run 自行早退，不空转消耗 credit
            await asyncio.sleep(6 * 3600)
    finally:
        _watchlist_monitor_stop.set()
        self_heal.cancel()


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
