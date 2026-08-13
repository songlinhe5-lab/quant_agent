"""FMP Prometheus 指标（子服务自包含，零 backend 依赖）

随子服务独立暴露 /metrics，主服务 system.py 经 HTTP scrape 观测 FMP 配额与健康状况。
共 14 个指标，覆盖：请求量 / 限流 / credit 预算 / 延迟 / 健康 / 兜底降级。
"""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# 独立 registry（不污染主服务默认 registry）
registry = CollectorRegistry()

# ── 1. 请求量 ──
FMP_REQUESTS_TOTAL = Counter("fmp_requests_total", "FMP 总请求数", ["action"], registry=registry)
# ── 2. 成功数 ──
FMP_SUCCESS_TOTAL = Counter("fmp_success_total", "FMP 成功响应数", ["action"], registry=registry)
# ── 3. 失败数 ──
FMP_ERROR_TOTAL = Counter("fmp_error_total", "FMP 失败响应数", ["action", "category"], registry=registry)
# ── 4. 429 限流命中 ──
FMP_RATE_LIMIT_TOTAL = Counter("fmp_rate_limit_total", "FMP 429 限流命中次数", registry=registry)
# ── 5. credit 累计消耗 ──
FMP_CREDIT_SPENT_TOTAL = Counter(
    "fmp_credit_spent_total", "FMP 累计 credit 消耗（跨日不清零，供 increase 查询）", registry=registry
)
# ── 6. credit 当日剩余 ──
FMP_CREDIT_REMAINING = Gauge("fmp_credit_remaining", "FMP 当日剩余 credit 预算", registry=registry)
# ── 7. credit 每日上限 ──
FMP_CREDIT_LIMIT = Gauge("fmp_credit_limit", "FMP 每日 credit 上限", registry=registry)
# ── 8. 请求延迟 histogram ──
FMP_REQUEST_LATENCY = Histogram("fmp_request_latency_seconds", "FMP 请求延迟分布", ["action"], registry=registry)
# ── 9. 自愈回路 P99 ──
FMP_HEAL_P99 = Gauge("fmp_heal_p99_seconds", "FMP 写链路自愈探测 P99（子服务侧就地探测）", registry=registry)
# ── 10. 自愈退避时长 ──
FMP_BACKOFF_SECONDS = Gauge("fmp_backoff_seconds", "FMP 自愈退避当前时长（秒）", registry=registry)
# ── 11. 熔断状态 ──
FMP_CIRCUIT_STATE = Gauge(
    "fmp_circuit_state", "FMP 熔断器状态 (0=closed,1=half_open,2=open)", ["service"], registry=registry
)
# ── 12. 缓存命中 ──
FMP_CACHE_HIT_TOTAL = Counter("fmp_cache_hit_total", "FMP 财报缓存命中数（子服务写缓存后观测）", registry=registry)
# ── 13. 批量拉取标的数 ──
FMP_BATCH_SYMBOLS_TOTAL = Counter("fmp_batch_symbols_total", "FMP 盘后批量拉取标的计数", registry=registry)
# ── 14. 数据源健康 ──
FMP_UP = Gauge("fmp_up", "FMP 数据源可用性 (1=可达,0=异常)", registry=registry)
# ── 15. 进程线程水位 (DIST-SEC-01 延伸：让 Grafana 也能直接 scrape 线程数) ──
PROCESS_THREADS = Gauge("process_threads", "子服务当前进程 OS 线程数（/proc/self/task 视角）", registry=registry)
PROCESS_THREAD_WARN = Gauge(
    "process_thread_warn_threshold", "子服务线程数告警阈值（超过即 degraded）", registry=registry
)


def set_process_thread_metrics(count: int, warn_threshold: int) -> None:
    """刷新子服务进程线程水位指标。"""
    PROCESS_THREADS.set(count)
    PROCESS_THREAD_WARN.set(warn_threshold)


def observe_credit_consume(delta: int, remaining: int, limit: int) -> None:
    """消费 credit 时调用：delta 为本次消耗增量（>0）。"""
    if delta > 0:
        FMP_CREDIT_SPENT_TOTAL.inc(delta)
    FMP_CREDIT_REMAINING.set(remaining)
    FMP_CREDIT_LIMIT.set(limit)


def set_credit_gauges(spent_total: int, remaining: int, limit: int) -> None:
    """兜底同步：用当前累计值直接刷新 Gauge（Counter 仍走 observe_credit_consume 增量）。"""
    FMP_CREDIT_REMAINING.set(remaining)
    FMP_CREDIT_LIMIT.set(limit)
