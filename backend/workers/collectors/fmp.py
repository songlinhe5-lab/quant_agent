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
# 网络抖动失败计数：ping 健康但 set 偶发超时的瞬态失败，不计入暂停阈值（避免毛刺误暂停丢 credit）
_jitter_fails: int = 0
# 滑动窗口 P99 劣化信号：由 _self_heal_loop 写入，True=判定写链路慢（应暂停），False=纯网络抖（不暂停）
_lat_degraded: bool = False
_lat_window_p99: float = 0.0  # 最近窗口 P99 估算值（Gauge 交叉校验用）

_FMP_REDIS_TTL = 24 * 3600  # 财报缓存 1 天
_BATCH_LIMIT = 4  # 每标的拉取的季度数（控制 credit：income_statement 1 call = 数 credit）
# FMP credit 计费校准（防预算击穿 / 防预算误估浪费容量）：
# 官方事实：免费档 = 250 requests/day，按 HTTP 请求次数计点（绝大多数端点 1 请求 = 1 credit）。
# 本守护每标的调用 income_statement + profile 共 2 个独立端点（见 _cache_financials），
# 故单 symbol 真实消耗 = _FMP_CALLS_PER_SYMBOL × _FMP_CREDIT_PER_CALL = 2 × 1 = 2 credit。
# 旧实现硬编码 used=4（"约2+约2"）实为 2 倍高估，按日预算 200 仅能拉 50 只而非 100 只 —— 浪费一半容量。
# 二者均 env 化，防御未来端点计费粒度变化或新增端点。
_FMP_CREDIT_PER_CALL = int(os.environ.get("FMP_CREDIT_PER_CALL", "1"))  # 单端点点数（FMP 标准端点=1）
# 每 symbol 调用的端点数（income_statement + profile）。注意：FMP 官方 FAQ 明确
# "One request counts as one API call"，limit 参数不影响计费粒度（无论 limit=4 还是 100 都只算 1 call），
# 故此处恒为 2，不因 limit 调整而 +1（已核实，勿凭直觉改）。
_FMP_CALLS_PER_SYMBOL = int(os.environ.get("FMP_CALLS_PER_SYMBOL", "2"))  # 每 symbol 调用的端点数（statement+profile）
# 自愈退避天花板（秒）：默认 300s（5min），可按 Redis SLA 级别经环境变量下调/上调。
# Grafana 侧「HEAL_BACKOFF_CAP」模板变量仅作展示锚点，真正生效以此 env 为准。
_HEAL_BACKOFF_CAP = float(os.environ.get("FMP_HEAL_BACKOFF_CAP", "300"))

# 自愈 P99 劣化判定阈值（秒）与持续窗口（秒）—— 对应 Grafana Panel 8 告警语义，
# 但此处为 Python 侧动态归因告警（触发时附带同窗 persist_fails / ping 延迟，区分网络抖 vs 写链路慢）。
_HEAL_P99_THRESHOLD = 0.5
_HEAL_P99_SUSTAIN = 300.0  # 持续 5min 才判定劣化（过滤偶发毛刺）
# 网络抖窗口的立即重试参数（env 热配，与 HEAL_BACKOFF_CAP 统一）：单次 set 失败后最多重试次数与每次退避（秒），提升瞬态恢复率
# _JITTER_RETRY 为可变运行时变量（自愈调参控制器会按成功率自适应调整），env 仅给初值与上下限。
_JITTER_RETRY = int(os.environ.get("FMP_JITTER_RETRY", "3"))
_JITTER_RETRY_MIN = int(os.environ.get("FMP_JITTER_RETRY_MIN", "1"))
_JITTER_RETRY_MAX = int(os.environ.get("FMP_JITTER_RETRY_MAX", "8"))
_JITTER_RETRY_BACKOFF = float(os.environ.get("FMP_JITTER_RETRY_BACKOFF", "0.2"))
# 自愈调参控制器自适应参数
_TUNE_INTERVAL = 300.0  # 每 5min 评估一次成功率
_TUNE_SUCCESS_LOW = 0.5  # 成功率 <50% → 重试性价比低，下调重试次数
_TUNE_SUCCESS_HIGH = 0.9  # 成功率 >90% → 重试高效，上调重试次数
_TUNE_WINDOW = 3600.0  # 统计窗口 1h（与 Grafana Panel 13 口径一致）
# 滞回（hysteresis）：成功率需在 50%~90% 区间外持续 _TUNE_HYSTERESIS_ROUNDS 轮才动作，
# 防边界抖动（如 49%↔51% 反复横跳）导致 _JITTER_RETRY 反复 ±1 振荡。
_TUNE_HYSTERESIS_ROUNDS = int(os.environ.get("FMP_JITTER_TUNE_HYST_ROUNDS", "3"))
# 滞回连击计数（进程内）：连续落在低/高区外的轮次数，达标才调参
_TUNE_LOW_STREAK: int = 0
_TUNE_HIGH_STREAK: int = 0

# 进程内重试成功率滑动统计：记录 (monotonic_ts, kind) kind∈{"recovered","jitter"}
_jitter_stats: list[tuple[float, str]] = []

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
    # 估算 credit：按实际调用的端点数 × 单端点点数（FMP 免费档按请求次数计点）。
    # income_statement + profile 共 _FMP_CALLS_PER_SYMBOL 个独立 GET，各 _FMP_CREDIT_PER_CALL 点。
    used = _FMP_CALLS_PER_SYMBOL * _FMP_CREDIT_PER_CALL
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


async def _do_set_credit() -> bool:
    """单次 Redis 持久化写入（不含重试/归因）。返回 True=成功。"""
    try:
        await redis_client.set(
            _credit_redis_key(_credit_reset_date),
            str(_credit_spent_today),
            ex=25 * 3600,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


async def _persist_credit() -> bool:
    """将当日 credit 消耗持久化到 Redis（ex=25h 自然过期，进程重启不丢进度）。

    自愈写重试：网络抖（_lat_degraded=False）时，单次 set 失败立即重试若干次
    （短间隔），提升瞬态恢复率，重试耗尽才记 _jitter_fails（不暂停）；
    写链路慢（_lat_degraded=True）时不重试（避免雪崩），直接计入暂停阈值。
    连续写入失败达 _PERSIST_FAIL_THRESHOLD 次 → 升 P1 告警并暂停守护；
    恢复成功时清零计数/标记并解除暂停（自愈）。
    返回 True=写入成功，False=失败。
    """
    global _persist_fails, _persist_fail_alerted, _collector_paused
    # 抖动窗口：立即重试，吞掉瞬态失败；写链路慢窗口：单次即判定，不重试
    _max_retry = _JITTER_RETRY if not _lat_degraded else 0
    for _attempt in range(1 + _max_retry):
        if await _do_set_credit():
            # 抖动重试挽回：首次尝试即成功(_attempt=0)不计数；靠重试才成功(_attempt>=1)记一次挽回
            if _attempt >= 1:
                try:
                    from backend.core.metrics import FMP_JITTER_RETRY_RECOVERED

                    FMP_JITTER_RETRY_RECOVERED.inc()
                    _jitter_stats.append((time.monotonic(), "recovered"))
                except Exception:  # noqa: BLE001
                    pass
            # 恢复成功 → 清零失败计数与告警标记，解除暂停（自愈）
            if _persist_fails > 0 or _collector_paused:
                logger.info(
                    f"[FMP Collector] Redis 持久化恢复"
                    f"（此前 {_persist_fails} 次失败，paused={_collector_paused}，"
                    f"本次第{_attempt}次尝试成功）→ 守护自愈重启"
                )
            _persist_fails = 0
            _persist_fail_alerted = False
            _jitter_fails = 0  # 写链路恢复，抖动计数一并清零
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
        # 本次 set 失败：写链路慢窗口直接跳出重试（不雪崩）；抖动窗口短暂退避后重试
        if _max_retry > 0:
            await asyncio.sleep(_JITTER_RETRY_BACKOFF)
    # 全部重试耗尽仍失败 → 归因分流
    try:
        _retry_ctx = "" if _lat_degraded else f"（网络抖重试 {_max_retry} 次仍失败，不暂停）"
        _err = RuntimeError(_retry_ctx)
    except Exception as e:  # noqa: BLE001
        _err = e
    # 归因分流：写链路慢（_lat_degraded=True，ping P99 高且 set 失败）→ 计入暂停阈值；
    # 纯网络抖动（ping 健康但 set 偶发超时）→ 仅记 _jitter_fails，不暂停，避免毛刺误丢 credit。
    if _lat_degraded:
        _persist_fails += 1
        logger.warning(
            f"[FMP Collector] credit 持久化失败（写链路慢 {_persist_fails}/{_PERSIST_FAIL_THRESHOLD}）{_retry_ctx}"
        )
        try:
            from backend.core.metrics import FMP_PERSIST_FAILS

            FMP_PERSIST_FAILS.set(_persist_fails)  # 实时暴露连续失败数（Grafana 趋势）
        except Exception:  # noqa: BLE001
            pass
    else:
        _jitter_fails += 1
        logger.warning(f"[FMP Collector] credit 持久化瞬态失败（网络抖，不暂停 {_jitter_fails} 次）{_retry_ctx}")
        try:
            from backend.core.metrics import FMP_PERSIST_JITTER_FAILS

            FMP_PERSIST_JITTER_FAILS.set(_jitter_fails)
            _jitter_stats.append((time.monotonic(), "jitter"))
        except Exception:  # noqa: BLE001
            pass
    # 重置对侧计数：写链路恢复后抖动计数清零，避免干扰；反之亦然
    if _lat_degraded:
        _jitter_fails = 0
    else:
        _persist_fails = 0
        _persist_fail_alerted = False
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
    上限由 FMP_HEAL_BACKOFF_CAP 控制（默认 5min）；一旦探测成功自愈，退避立即归零。
    每次轮询实测 Redis PING 延迟并写入 Gauge / Histogram，同时维护滑动窗口用于
    P99 劣化动态归因告警（触发时附同窗 persist_fails 与 ping 延迟，区分网络抖 vs 写链路慢）。
    """
    import time as _time

    from backend.core.redis_client import redis_client

    base = 30.0
    cap = _HEAL_BACKOFF_CAP
    backoff = base
    # 滑动窗口：记录 (monotonic_ts, latency_or_None)，用于 P99 持续劣化判定
    _lat_window: list[tuple[float, float | None]] = []
    _degrade_alerted = False
    try:
        from backend.core.metrics import (
            FMP_HEAL_BACKOFF,
            FMP_HEAL_P99,
            FMP_REDIS_PING_LATENCY,
            FMP_REDIS_PING_LATENCY_HIST,
        )

        _have_backoff_gauge = True
    except Exception:  # noqa: BLE001
        _have_backoff_gauge = False
    while True:
        # 实测 Redis PING 往返延迟（无论是否暂停都探，喂延迟趋势定位抖动来源）
        _now = _time.monotonic()
        _sample: float | None = None
        try:
            _t0 = _time.monotonic()
            await redis_client.ping()
            _lat = _time.monotonic() - _t0
            _sample = _lat
            if _have_backoff_gauge:
                FMP_REDIS_PING_LATENCY.set(round(_lat, 4))
                try:
                    FMP_REDIS_PING_LATENCY_HIST.observe(_lat)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass  # 连 ping 都失败，延迟不写，persist_fails 已体现故障
        _lat_window.append((_now, _sample))
        # 仅保留最近 _HEAL_P99_SUSTAIN 秒的样本
        _cut = _now - _HEAL_P99_SUSTAIN
        _lat_window = [(t, v) for (t, v) in _lat_window if t >= _cut]
        # P99 估算：窗口内有效样本取第 99 分位（样本不足则跳过）
        _valid = sorted(v for (_, v) in _lat_window if v is not None)
        if len(_valid) >= 10:
            _p99 = _valid[min(len(_valid) - 1, int(len(_valid) * 0.99))]
            globals()["_lat_window_p99"] = _p99
            if _have_backoff_gauge:
                try:
                    FMP_HEAL_P99.set(round(_p99, 4))  # 滑动窗口 P99 Gauge（与 Grafana histogram_quantile 交叉校验）
                except Exception:  # noqa: BLE001
                    pass
            if _p99 > _HEAL_P99_THRESHOLD:
                globals()["_lat_degraded"] = True  # 写链路慢信号 → 后续 set 失败才计入暂停阈值
                try:
                    from backend.core.metrics import FMP_LAT_DEGRADED

                    FMP_LAT_DEGRADED.set(1)
                except Exception:  # noqa: BLE001
                    pass
                if not _degrade_alerted:
                    _degrade_alerted = True
                    _avg = sum(_valid) / len(_valid)
                    # 归因：写链路慢（P99 高且后续 persist 会同步失败 → 应暂停）vs 纯抖动（persist 仍健康）
                    _cause = (
                        f"写链路慢/Redis 劣化（PING P99={_p99:.3f}s 持续 {int(_HEAL_P99_SUSTAIN)}s>"
                        f"{_HEAL_P99_THRESHOLD}s，后续持久化失败将触发暂停防丢失）"
                    )
                    try:
                        from backend.core.alert_models import NotificationPriority
                        from backend.services.alert.notification import notification_service

                        await notification_service.send_alert(
                            message=(
                                f"[FMP Collector] Redis P99 延迟持续劣化告警（写链路慢）\n"
                                f"窗口 {int(_HEAL_P99_SUSTAIN)}s 内 PING P99={_p99:.3f}s（> {_HEAL_P99_THRESHOLD}s），"
                                f"均值={_avg:.3f}s，当前 persist_fails={_persist_fails}，退避上限={cap:.0f}s。\n"
                                f"归因：{_cause}"
                            ),
                            priority=NotificationPriority.P1,
                            source="fmp-collector",
                        )
                    except Exception:  # noqa: BLE001
                        pass
            else:
                globals()["_lat_degraded"] = False  # P99 回落 → 视为纯网络抖窗口，set 失败不暂停
                try:
                    from backend.core.metrics import FMP_LAT_DEGRADED

                    FMP_LAT_DEGRADED.set(0)
                except Exception:  # noqa: BLE001
                    pass
                _degrade_alerted = False  # 重置，下次再劣化可再报
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
        if _have_backoff_gauge:
            try:
                FMP_HEAL_BACKOFF.set(backoff)
            except Exception:  # noqa: BLE001
                pass
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
    """解析 FMP 守护独立 watchlist，多源并集（去重保序）：

    源优先级（高优先源的 symbol 不会被低优先源覆盖，而是合并）：
    1. FMP_COLLECTOR_SYMBOLS (env, 逗号分隔) —— 运营显式指定，最高优先
    1.5 PORTFOLIO_SYMBOLS (env) / config/portfolio_symbols.txt (文件) —— 实盘持仓池并集
        （日后接入实盘持仓时启用：把账户 positions 导出为该文件或 env，自动纳入财报缓存，
         避免硬编码 4 只漏掉实盘标的；与既有源做并集而非取代）
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
    """对外暴露守护运行态（供 /observability 聚合，避免直接 import 私有全局变量）。"""
    return {
        "paused": _collector_paused,
        "persist_fails": _persist_fails,
        "persist_fail_threshold": _PERSIST_FAIL_THRESHOLD,
        "credit_spent_today": _credit_spent_today,
        "credit_reset_date": _credit_reset_date,
        "watchlist_size": len(_watchlist_cache),
        "watchlist_empty_warn": len(_watchlist_cache) == 0,
        "heal_backoff_cap": _HEAL_BACKOFF_CAP,
        "heal_backoff_threshold": _HEAL_P99_THRESHOLD,
        "heal_backoff_sustain": _HEAL_P99_SUSTAIN,
        "jitter_fails": _jitter_fails,
        "jitter_retry": _JITTER_RETRY,
        "jitter_retry_min": _JITTER_RETRY_MIN,
        "jitter_retry_max": _JITTER_RETRY_MAX,
        "jitter_retry_backoff": _JITTER_RETRY_BACKOFF,
        "jitter_tune_hyst_rounds": _TUNE_HYSTERESIS_ROUNDS,
        "jitter_tune_low_streak": _TUNE_LOW_STREAK,
        "jitter_tune_high_streak": _TUNE_HIGH_STREAK,
        "lat_degraded": _lat_degraded,
        "lat_window_p99": _lat_window_p99,
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
    try:
        from backend.core.metrics import FMP_WATCHLIST_EMPTY

        if not symbols:
            FMP_WATCHLIST_EMPTY.set(1)  # APM 告警：所有标的源均未配置，守护静默兜底未拉任何财报
            logger.error(
                "[FMP Collector] watchlist 为空（FMP_COLLECTOR_SYMBOLS/PORTFOLIO_SYMBOLS/"
                "WATCHLIST/FINNHUB_WS_SYMBOLS 均未配置任何源），守护静默兜底未拉取任何财报！"
            )
            return
        FMP_WATCHLIST_EMPTY.set(0)
    except Exception:  # noqa: BLE001
        if not symbols:
            logger.error("[FMP Collector] watchlist 为空，所有标的源均未配置")
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
        from backend.core.metrics import FMP_COLLECTOR_PAUSED, FMP_JITTER_RETRY_ACTIVE, FMP_WATCHLIST_EMPTY

        FMP_COLLECTOR_PAUSED.set(0)  # 启动基线：正常态
        FMP_JITTER_RETRY_ACTIVE.set(_JITTER_RETRY)  # 启动基线：当前生效重试次数
        FMP_WATCHLIST_EMPTY.set(0)  # 启动基线：watchlist 非空假设（首轮 _batch_run 会校正）
    except Exception:  # noqa: BLE001
        pass
    monitor = threading.Thread(target=_watch_watchlist_file, name="fmp-watchlist-mon", daemon=True)
    monitor.start()
    self_heal = asyncio.create_task(_self_heal_loop(), name="fmp-self-heal")
    tune = asyncio.create_task(_jitter_tune_loop(), name="fmp-jitter-tune")
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
        tune.cancel()


async def _jitter_tune_loop() -> None:
    """自愈调参控制器：周期性评估抖动重试成功率，闭环自适应 _JITTER_RETRY。

    每 _TUNE_INTERVAL 计算最近 _TUNE_WINDOW（1h）内成功率 = recovered/(recovered+jitter)：
      - 成功率 < _TUNE_SUCCESS_LOW(50%)：重试性价比低（抖动顽固），下调重试次数（下限 _JITTER_RETRY_MIN）
      - 成功率 > _TUNE_SUCCESS_HIGH(90%)：重试高效（瞬态抖动），上调重试次数（上限 _JITTER_RETRY_MAX）
    滞回（hysteresis）：成功率需在 50%~90% 区间外持续 _TUNE_HYSTERESIS_ROUNDS 轮才动作，
    防边界抖动反复横跳导致 _JITTER_RETRY 振荡。每次仅 ±1 步进，并记录至 collector_runtime 供 APM 观测。
    """
    import time as _time

    try:
        from backend.core.metrics import FMP_JITTER_RETRY_ACTIVE
    except Exception:  # noqa: BLE001
        FMP_JITTER_RETRY_ACTIVE = None

    while True:
        await asyncio.sleep(_TUNE_INTERVAL)
        try:
            _now = _time.monotonic()
            _cut = _now - _TUNE_WINDOW
            # 仅保留窗口内样本
            globals()["_jitter_stats"] = [(t, k) for (t, k) in _jitter_stats if t >= _cut]
            _stats = _jitter_stats
            _rec = sum(1 for (_, k) in _stats if k == "recovered")
            _jit = sum(1 for (_, k) in _stats if k == "jitter")
            _total = _rec + _jit
            if _total < 5:
                continue  # 样本不足，不调参（防噪声误判）
            _rate = _rec / _total
            # 滞回判定：仅当成功率在阈值区外时累计连击；一旦回到区间内立即清零对侧连击
            global _TUNE_LOW_STREAK, _TUNE_HIGH_STREAK
            if _rate < _TUNE_SUCCESS_LOW:
                _TUNE_LOW_STREAK += 1
                _TUNE_HIGH_STREAK = 0
            elif _rate > _TUNE_SUCCESS_HIGH:
                _TUNE_HIGH_STREAK += 1
                _TUNE_LOW_STREAK = 0
            else:
                # 落在死区内：双向清零，不累积任何方向连击
                _TUNE_LOW_STREAK = 0
                _TUNE_HIGH_STREAK = 0
                continue
            # 未达滞回轮次门槛：仅记录不调参，防边界反复横跳
            if _rate < _TUNE_SUCCESS_LOW and _TUNE_LOW_STREAK < _TUNE_HYSTERESIS_ROUNDS:
                logger.info(
                    f"[FMP 调参] 成功率 {_rate:.2f} < {_TUNE_SUCCESS_LOW}，但连击 {_TUNE_LOW_STREAK}/"
                    f"{_TUNE_HYSTERESIS_ROUNDS} 未达滞回门槛，暂不下调"
                )
                continue
            if _rate > _TUNE_SUCCESS_HIGH and _TUNE_HIGH_STREAK < _TUNE_HYSTERESIS_ROUNDS:
                logger.info(
                    f"[FMP 调参] 成功率 {_rate:.2f} > {_TUNE_SUCCESS_HIGH}，但连击 {_TUNE_HIGH_STREAK}/"
                    f"{_TUNE_HYSTERESIS_ROUNDS} 未达滞回门槛，暂不上调"
                )
                continue
            _old = _JITTER_RETRY
            if _rate < _TUNE_SUCCESS_LOW and _JITTER_RETRY > _JITTER_RETRY_MIN:
                globals()["_JITTER_RETRY"] = _JITTER_RETRY - 1
                logger.info(
                    f"[FMP 调参] 成功率 {_rate:.2f} < {_TUNE_SUCCESS_LOW} 连击 {_TUNE_LOW_STREAK} 达标，"
                    f"下调 FMP_JITTER_RETRY {_old} → {_JITTER_RETRY}（抖动顽固，重试性价比低）"
                )
            elif _rate > _TUNE_SUCCESS_HIGH and _JITTER_RETRY < _JITTER_RETRY_MAX:
                globals()["_JITTER_RETRY"] = _JITTER_RETRY + 1
                logger.info(
                    f"[FMP 调参] 成功率 {_rate:.2f} > {_TUNE_SUCCESS_HIGH} 连击 {_TUNE_HIGH_STREAK} 达标，"
                    f"上调 FMP_JITTER_RETRY {_old} → {_JITTER_RETRY}（瞬态抖动，重试高效）"
                )
            # 动作后清零连击，避免连续多轮重复步进（每轮仅 ±1 已足够，下轮重新计连击）
            _TUNE_LOW_STREAK = 0
            _TUNE_HIGH_STREAK = 0
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[FMP 调参] 评估异常: {e}")
        finally:
            # 实时暴露当前生效值（Grafana 看自适应轨迹是否与成功率拐点吻合）
            if FMP_JITTER_RETRY_ACTIVE is not None:
                try:
                    FMP_JITTER_RETRY_ACTIVE.set(_JITTER_RETRY)
                except Exception:  # noqa: BLE001
                    pass


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
