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
    ["symbol", "check_type"],  # check_type: "quality_check" | "adjustment" | "suspension"  # noqa: E501
)

MARKET_DATA_ANOMALY_TOTAL = Counter(
    "quant_market_data_anomaly_total",
    "行情数据异常检测总数",
    ["symbol", "severity"],  # severity: "critical" | "warning"
)
