"""
Quant Agent Prometheus 自定义指标定义（BE-06）

对齐 docs/10 §1.4 + docs/08 可观测性规范：
- 行情延迟分位数（Summary）
- WebSocket 连接数（Gauge）
- Redis 队列深度（Gauge）
- 熔断器状态（Gauge）
- 客户端 APM 心跳（Counter）

用法：
    from backend.core.metrics import MARKET_QUOTE_LATENCY, REDIS_QUEUE_DEPTH

    MARKET_QUOTE_LATENCY.labels(source="futu", symbol="US.AAPL").observe(0.023)
    REDIS_QUEUE_DEPTH.labels(queue="quant:quotes:stream").set(42)
"""

from prometheus_client import Counter, Gauge, Histogram, Summary

# ==========================================
#  行情数据指标
# ==========================================

MARKET_QUOTE_LATENCY = Summary(
    "quant_market_quote_latency_seconds",
    "行情快照获取延迟（从数据源到 Redis 写入的全链路耗时）",
    ["source", "symbol"],
)

MARKET_QUOTE_STALENESS = Gauge(
    "quant_market_quote_staleness_seconds",
    "行情数据最后更新时间距当前的秒数（超过 30s 视为 stale）",
    ["symbol"],
)

MARKET_QUOTE_TOTAL = Counter(
    "quant_market_quote_total",
    "行情快照总接收数量",
    ["source", "symbol"],
)

MARKET_KLINE_FETCH_LATENCY = Histogram(
    "quant_market_kline_fetch_seconds",
    "K线数据获取延迟（含三级缓存命中路径）",
    ["source", "period"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")],
)

# ==========================================
#  WebSocket 指标
# ==========================================

WS_ACTIVE_CONNECTIONS = Gauge(
    "quant_ws_active_connections",
    "当前活跃的行情 WebSocket 连接数",
)

WS_MESSAGES_SENT = Counter(
    "quant_ws_messages_sent_total",
    "WebSocket 消息发送总数",
    ["type"],  # "quote" | "kline" | "system" | "error"
)

WS_MESSAGES_DROPPED = Counter(
    "quant_ws_messages_dropped_total",
    "WebSocket 背压丢弃消息总数（慢客户端）",
)

WS_SUBSCRIPTIONS = Gauge(
    "quant_ws_subscriptions",
    "当前活跃的行情订阅总数",
)

# ==========================================
#  Redis 指标
# ==========================================

REDIS_QUEUE_DEPTH = Gauge(
    "quant_redis_queue_depth",
    "Redis Stream / List 队列深度（消息积压数量）",
    ["queue"],
)

REDIS_OPERATION_LATENCY = Summary(
    "quant_redis_operation_latency_seconds",
    "Redis 操作延迟（读写/PubSub/Stream）",
    ["operation"],  # "hset" | "publish" | "xadd" | "get" | "pipeline"
)

REDIS_ERRORS = Counter(
    "quant_redis_errors_total",
    "Redis 操作错误总数",
    ["operation"],
)

# ==========================================
#  熔断器指标
# ==========================================

CIRCUIT_BREAKER_STATE = Gauge(
    "quant_circuit_breaker_state",
    "熔断器当前状态（0=closed, 1=half_open, 2=open）",
    ["service"],
)

CIRCUIT_BREAKER_TRANSITIONS = Counter(
    "quant_circuit_breaker_transitions_total",
    "熔断器状态转换次数",
    ["service", "from_state", "to_state"],
)

# ==========================================
#  客户端 APM 指标
# ==========================================

CLIENT_HEARTBEAT_TOTAL = Counter(
    "quant_client_heartbeat_total",
    "客户端 APM 心跳接收总数",
    ["platform"],
)

# OBS-03: Web Vitals（单位见 metric 名；CLS 无量纲用 float）
CLIENT_WEB_VITAL_LCP = Histogram(
    "quant_client_web_vital_lcp_seconds",
    "客户端 LCP（Largest Contentful Paint）",
    ["platform"],
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 4.0, 8.0, float("inf")],
)

CLIENT_WEB_VITAL_CLS = Histogram(
    "quant_client_web_vital_cls",
    "客户端 CLS（Cumulative Layout Shift）",
    ["platform"],
    buckets=[0.01, 0.05, 0.1, 0.15, 0.25, 0.5, 1.0, float("inf")],
)

CLIENT_WEB_VITAL_INP = Histogram(
    "quant_client_web_vital_inp_seconds",
    "客户端 INP（Interaction to Next Paint）",
    ["platform"],
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, float("inf")],
)

CLIENT_WEB_VITAL_TTFB = Histogram(
    "quant_client_web_vital_ttfb_seconds",
    "客户端 TTFB（Time to First Byte）",
    ["platform"],
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, float("inf")],
)

# ==========================================
#  数据源监控指标 (Phase 3)
# ==========================================

# 延迟分布直方图（按数据源）
DATASOURCE_LATENCY = Histogram(
    "quant_datasource_latency_milliseconds",
    "数据源请求延迟分布（毫秒）",
    ["source", "action"],
    buckets=[50, 100, 150, 200, 250, 300, 500, 1000, 2000, float("inf")],
)

# 错误率计数器（按数据源）
DATASOURCE_ERRORS = Counter(
    "quant_datasource_errors_total",
    "数据源错误总数",
    ["source", "error_type"],  # error_type: rate_limit, timeout, network, circuit_open, etc.
)

# 限流计数器（按数据源）
DATASOURCE_RATE_LIMITS = Counter(
    "quant_datasource_rate_limits_total",
    "数据源限流次数",
    ["source", "category"],  # category: 429, 403, 402
)

# 可用性状态（按数据源）
DATASOURCE_AVAILABILITY = Gauge(
    "quant_datasource_availability",
    "数据源可用性状态 (1=可用，0=不可用)",
    ["source"],
)

# ==========================================
#  业务聚合 Facade 指标 (BE-ARCH-06d)
#  —— 与上面「数据源层」指标分层：此处观测的是 Facade 业务聚合行为，而非单源取数
# ==========================================

# Facade 多源融合次数（按 action + 融合模式：single/multi + 是否触发偏差告警）
DATASOURCE_FACADE_MERGE = Counter(
    "quant_datasource_facade_merge_total",
    "业务聚合 Facade 融合调用次数（单源直采/多源融合）",
    ["action", "mode"],  # mode: single | multi | deviation
)

# Facade 多源报价偏差告警次数（QUOTE 多源价差超阈值）
DATASOURCE_QUOTE_DEVIATION = Counter(
    "quant_datasource_quote_deviation_total",
    "Facade 多源报价偏差告警次数（超过 DATASOURCE_QUOTE_DEVIATION_PCT 阈值）",
    ["source"],  # 作为主源（新鲜度最高者）标注
)

# ==========================================
#  Agent / LLM 指标
# ==========================================

LLM_REQUEST_LATENCY = Histogram(
    "quant_llm_request_seconds",
    "LLM API 请求延迟",
    ["model"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, float("inf")],
)

LLM_TOKEN_USAGE = Counter(
    "quant_llm_tokens_total",
    "LLM Token 消耗总量",
    ["model", "type"],  # type: "prompt" | "completion"
)

AGENT_TOOL_CALLS = Counter(
    "quant_agent_tool_calls_total",
    "Agent Tool 调用总数",
    ["tool", "status"],  # status: "success" | "error" | "timeout"
)

# ==========================================
#  Futu OpenD 连接指标 (BE-03)
# ==========================================

FUTU_CONNECTION_STATUS = Gauge(
    "quant_futu_connection_status",
    "Futu OpenD 连接状态（0=断开, 1=正常）",
)

FUTU_RECONNECT_TOTAL = Counter(
    "quant_futu_reconnect_total",
    "Futu OpenD 重连尝试总次数",
)

FUTU_RECONNECT_FAILURES = Counter(
    "quant_futu_reconnect_failures_total",
    "Futu OpenD 重连失败次数",
)

FUTU_RECONNECT_LATENCY = Histogram(
    "quant_futu_reconnect_latency_seconds",
    "Futu OpenD 重连耗时（从断开到恢复的总时间）",
    buckets=[1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, float("inf")],
)

# ==========================================
#  K线缓存命中指标 (BE-02)
# ==========================================

KLINE_CACHE_HIT = Counter(
    "quant_kline_cache_hit_total",
    "K线缓存命中次数",
    ["tier"],  # "redis" | "parquet" | "miss"
)

KLINE_CACHE_QUERY_LATENCY = Histogram(
    "quant_kline_cache_query_seconds",
    "K线查询延迟（含缓存路由）",
    ["tier"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")],
)

# ==========================================
#  数据质量指标 (BE-16)
# ==========================================

MARKET_DATA_CORRECTION_TOTAL = Counter(
    "quant_market_data_correction_total",
    "行情数据正确性检查总次数",
    [
        "symbol",
        "check_type",
    ],  # check_type: "quality_check" | "adjustment" | "suspension"  # noqa: E501
)

MARKET_DATA_ANOMALY_TOTAL = Counter(
    "quant_market_data_anomaly_total",
    "行情数据异常检测总数",
    ["symbol", "severity"],  # severity: "critical" | "warning"
)

# ==========================================
#  数据源限流指标 (RL-10)
# ==========================================

DS_RATE_LIMIT_TOTAL = Counter(
    "ds_rate_limit_total",
    "数据源限流触发总次数",
    ["source", "category"],  # category: "rate_limit" | "quota_exhausted" | "ip_blocked"
)

DS_RATE_LIMIT_THROTTLED_SECONDS = Gauge(
    "ds_rate_limit_throttled_seconds",
    "数据源当前退避剩余秒数（0=无限流）",
    ["source"],
)

DS_RATE_LIMIT_ESTIMATED_RPM = Gauge(
    "ds_rate_limit_estimated_rpm",
    "数据源推测的限流阈值 RPM",
    ["source"],
)

DS_RATE_LIMIT_EFFECTIVE_RPM = Gauge(
    "ds_rate_limit_effective_rpm",
    "数据源当前实际有效 RPM",
    ["source"],
)

DS_BACKOFF_STATE = Gauge(
    "ds_backoff_state",
    "数据源退避策略状态 (0=none, 1=linear, 2=exponential, 3=adaptive)",
    ["source"],
)

# ==========================================
#  数据湖快照（DQ-03）
# ==========================================

DATALAKE_SNAPSHOT_CREATED = Counter(
    "datalake_snapshot_created_total",
    "数据湖日快照创建次数",
    ["status"],
)

DATALAKE_SNAPSHOT_READ = Counter(
    "datalake_snapshot_read_total",
    "快照 K 线读取次数",
    ["result"],
)

DATALAKE_RETENTION_RUNS = Counter(
    "datalake_retention_runs_total",
    "快照保留任务执行次数",
)

DATALAKE_LATEST_AGE_DAYS = Gauge(
    "datalake_latest_snapshot_age_days",
    "最新 published 快照距今天数（告警用）",
)

# ==========================================
#  数据质量（SVC-04 / DQ-04）
# ==========================================

DATA_QUALITY_DIRTY_RATE = Gauge(
    "quant_data_quality_dirty_rate",
    "数据源脏数据率（异常记录/总记录）",
    ["source"],
)

DATA_QUALITY_COMPLETENESS = Gauge(
    "quant_data_quality_completeness_rate",
    "数据源字段完整率（有效记录/总记录）",
    ["source"],
)

DATA_QUALITY_TOTAL_RECORDS = Gauge(
    "quant_data_quality_total_records",
    "数据源累计校验记录数",
    ["source"],
)

DATA_QUALITY_ANOMALY_COUNT = Gauge(
    "quant_data_quality_anomaly_count",
    "数据源累计异常记录数",
    ["source"],
)

DATA_QUALITY_MISSING_FIELDS = Gauge(
    "quant_data_quality_missing_field_count",
    "字段缺失累计次数",
    ["source"],
)

DATA_QUALITY_PRICE_ANOMALY = Gauge(
    "quant_data_quality_price_anomaly_count",
    "价格异常（零价/跳变/负值）累计次数",
    ["source"],
)

DATA_QUALITY_STALE_COUNT = Gauge(
    "quant_data_quality_stale_count",
    "时间戳过期累计次数",
    ["source"],
)

DATA_QUALITY_LATENCY_MS = Gauge(
    "quant_data_quality_avg_latency_ms",
    "数据平均延迟（毫秒）",
    ["source"],
)

DATA_QUALITY_LEVEL = Gauge(
    "quant_data_quality_level",
    "质量等级 (0=good 1=degraded 2=poor 3=unusable)",
    ["source"],
)

DATA_QUALITY_CHECKS = Counter(
    "quant_data_quality_checks_total",
    "质量校验的次数",
    ["source", "result"],
)

# ==========================================
#  分布式节点指标 (DIST-20)
# ==========================================

DIST_NODE_HEARTBEAT = Gauge(
    "quant_dist_node_heartbeat_timestamp",
    "节点最后心跳时间戳 (Unix epoch)",
    ["node_id", "region"],
)

DIST_NODE_STATUS = Gauge(
    "quant_dist_node_status",
    "节点状态 (0=dead, 1=draining, 2=active)",
    ["node_id", "region"],
)

DIST_NODE_ALIVE = Gauge(
    "quant_dist_node_alive_count",
    "当前存活的节点数量",
    ["capability"],
)

DIST_YF_FAILOVER_TOTAL = Counter(
    "quant_dist_yf_failover_total",
    "YF 路由器 failover 事件总数",
    ["from_node", "to_node", "reason"],
)

DIST_YF_429_TOTAL = Counter(
    "quant_dist_yf_429_total",
    "YF 节点 429 限流响应总数",
    ["node_id"],
)

DIST_YF_STALE_TOTAL = Counter(
    "quant_dist_yf_stale_fallback_total",
    "YF STALE 缓存降级返回总数",
    ["cache_key"],
)

DIST_AK_STALE_TOTAL = Counter(
    "quant_dist_ak_stale_fallback_total",
    "AKShare STALE 缓存降级返回总数 (CN 断连)",
    ["action"],
)

# ==========================================
#  Finnhub WS 实时价命中/降级指标 (BE-ARCH-05)
# ==========================================

TICK_CACHE_HITS = Counter(
    "quant_tick_cache_hits_total",
    "Finnhub WS 实时价命中次数（quote 走 tick_cache 优先返回）",
)

TICK_CACHE_MISSES = Counter(
    "quant_tick_cache_misses_total",
    "Finnhub WS 实时价降级次数（tick_cache 未命中，走 REST 快照）",
)

TICK_CACHE_HIT_RATE = Gauge(
    "quant_tick_cache_hit_rate",
    "Finnhub WS 实时价命中率 (0~1，无查询时为 NaN)",
)

# ==========================================
#  FMP collector 业务编排指标 (BE-ARCH-05 · Phase 5 下沉后重建)
# ==========================================
# 责任边界（与 data_subservice 物理隔离，勿混淆命名空间）：
#   - 本文件 quant_fmp_collector_*  → 主服务【业务编排层】：watchlist 池管理、
#     盘后批次调度成败、财报写 Redis 缓存健康。这些指标的产生者是
#     backend/workers/collectors/fmp.py，与数据源无关。
#   - 子服务 fmp_*（data_subservice/_internal/metrics.py，独立 registry，
#     经 GET {FMP_REMOTE_URL}/metrics 暴露）→【数据源连接层】：REST 请求量、
#     429 限流、credit 配额、请求延迟、数据源 up。
#   Grafana dashboard 需同时挂两个 Prometheus job 才能拼出全貌，
#   面板标题已用「业务」/「数据源」前缀区分，避免运维误判归因。
#
# [REMOVED-Phase5] 以下指标随自愈回路下沉子服务后已删除，勿在主服务重建：
#   quant_fmp_collector_credit_spent_total  → 子服务 fmp_credit_spent_total
#   quant_fmp_collector_paused / persist_fails / persist_jitter_fails
#   quant_fmp_collector_heal_p99_seconds / heal_backoff_seconds
#   quant_fmp_collector_redis_ping_latency_seconds(_hist)
#   quant_fmp_collector_lat_degraded / jitter_retry_recovered_total / jitter_retry_active
# 原因：Redis 写链路自愈已收敛到主服务通用健康检查，credit 配额归子服务权威。

FMP_BATCH_RUNS_TOTAL = Counter(
    "quant_fmp_collector_batch_runs_total",
    "FMP collector 盘后批次执行计数（按结果分类：completed=正常跑完 / skipped_market_hours=盘中早退 "
    "/ skipped_empty_watchlist=标的池空 / skipped_budget=子服务 credit 预算耗尽）",
    ["result"],
)

FMP_SYMBOLS_CACHED_TOTAL = Counter(
    "quant_fmp_collector_symbols_cached_total",
    "FMP collector 财报成功写入 Redis 的标的次数（业务产出真相源，与 watchlist_size 对账可得覆盖率）",
)

FMP_SYMBOLS_FAILED_TOTAL = Counter(
    "quant_fmp_collector_symbols_failed_total",
    "FMP collector 标的处理失败次数（按根因：fetch=子服务取数失败/限流 / redis=本地缓存写入失败）",
    ["reason"],
)

FMP_BATCH_DURATION = Histogram(
    "quant_fmp_collector_batch_duration_seconds",
    "FMP collector 单轮盘后批次耗时分布（含标的间 sleep 留白，用于评估批次是否溢出盘后窗口）",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
)

FMP_LAST_BATCH_TIMESTAMP = Gauge(
    "quant_fmp_collector_last_batch_timestamp_seconds",
    "FMP collector 上一轮批次完成的 Unix 时间戳（配合 time() - 该值 可告警守护静默/卡死）",
)

FMP_SUBSERVICE_UNREACHABLE = Gauge(
    "quant_fmp_collector_subservice_unreachable",
    "FMP collector 读取子服务 credit 快照失败（1=子服务不可达，预算决策已降级为本地估算；0=正常）",
)

FMP_WATCHLIST_EMPTY = Gauge(
    "quant_fmp_collector_watchlist_empty",
    "FMP collector watchlist 为空告警（所有标的源均未配置，守护静默兜底未拉任何财报 = 1）",
)

FMP_WATCHLIST_SIZE = Gauge(
    "quant_fmp_collector_watchlist_size",
    "FMP collector 当前生效 watchlist 标的池大小（多源并集；=0 即静默兜底，配合 watchlist_empty 告警定位配置遗漏）",
)

# [DEPRECATED-PATH] FMP_WATCHLIST_SIZE_SHIFT —— 进程内突变计数（当前单副本使用的真相源）。
# 未来真上多副本并行时，此 Counter 会被放大 N 倍（各副本各自 inc），应废弃并切换到
# Prometheus recording rule `config/prometheus_rules.yml` 中的 `fmp:watchlist_size_shift_flag`
# （server 端统一判定，零 exporter 耦合）。届时：
#   1. 取消 prometheus.yml 的 rule_files 注释并挂载 rules 文件；
#   2. 将 Panel 16 的 alert expr 从 increase(shift[1h]) 切到 fmp:watchlist_size_shift_flag；
#   3. 删除本 Counter 及其所有 inc() 调用。
# 当前（uvicorn --workers 1 单副本）保留使用，勿删。
FMP_WATCHLIST_SIZE_SHIFT = Counter(
    "quant_fmp_collector_watchlist_size_shift_total",
    "FMP collector watchlist 标的池大小突变计数（短时发生 ±50% 变化，提示账户调仓异常或文件误删）[DEPRECATED-PATH: 多副本改用 fmp:watchlist_size_shift_flag recording rule]",
)

FMP_WATCHLIST_FILE_DELETED = Counter(
    "quant_fmp_collector_watchlist_file_deleted_total",
    "FMP collector 监听的 watchlist/portfolio 文件被删除事件计数（根因分类：删文件 vs 调仓）",
)

# ==========================================
#  WebScrape (fetch_webpage) 抓取成功率插桩 (AGENTS.md §2.12 降级实证)
# ==========================================
# 目的：量化 PR Newswire / HKEX 披露易 等反爬域名的抓取失败率，验证 Jina→httpx
#       自动降级链的实际健康度。按 source(jina|httpx) × domain(域名) 维度计数，
#       跑一周后 `sum(rate(failed[7d])) / sum(rate(total[7d])) by (domain)` 即得真实失败率。
# 注意：这是纯计数插桩，不影响现有降级逻辑（Jina→httpx→建议 web_search 文案）。

WEB_SCRAPE_FETCH_TOTAL = Counter(
    "quant_webscrape_fetch_total",
    "fetch_webpage 网页抓取尝试总数（每次 run 对单 url 计 1 次，jina 与 httpx 各独立计数）",
    ["source", "domain"],  # source: "jina" | "httpx"；domain: urlparse(url).netloc
)

WEB_SCRAPE_FETCH_FAILED = Counter(
    "quant_webscrape_fetch_failed_total",
    "fetch_webpage 网页抓取失败数（反爬拦截 / 内容过短 / 网络异常 / 403-503 等均计入）",
    ["source", "domain", "reason"],  # reason: "anti_bot" | "too_short" | "http_error"
)
