"""
Prometheus 指标定义单元测试
覆盖: backend/core/metrics.py - 验证所有指标可被采集与标签绑定
"""

import os
import sys
from prometheus_client import Counter, Gauge, Histogram, Summary
from prometheus_client.registry import REGISTRY

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest


class TestMarketQuoteMetrics:
    """行情数据指标测试"""

    def test_market_quote_latency_is_summary(self):
        from backend.core.metrics import MARKET_QUOTE_LATENCY

        assert isinstance(MARKET_QUOTE_LATENCY, Summary)
        # 验证 observe 操作可执行
        MARKET_QUOTE_LATENCY.labels(source="futu", symbol="US.AAPL").observe(0.023)

    def test_market_quote_staleness_is_gauge(self):
        from backend.core.metrics import MARKET_QUOTE_STALENESS

        assert isinstance(MARKET_QUOTE_STALENESS, Gauge)
        MARKET_QUOTE_STALENESS.labels(symbol="HK.00700").set(42.0)

    def test_market_quote_total_is_counter(self):
        from backend.core.metrics import MARKET_QUOTE_TOTAL

        assert isinstance(MARKET_QUOTE_TOTAL, Counter)
        MARKET_QUOTE_TOTAL.labels(source="yfinance", symbol="US.TSLA").inc()

    def test_market_kline_fetch_latency_is_histogram(self):
        from backend.core.metrics import MARKET_KLINE_FETCH_LATENCY

        assert isinstance(MARKET_KLINE_FETCH_LATENCY, Histogram)
        MARKET_KLINE_FETCH_LATENCY.labels(source="futu", period="K_DAY").observe(0.05)


class TestWebSocketMetrics:
    """WebSocket 指标测试"""

    def test_ws_active_connections_is_gauge(self):
        from backend.core.metrics import WS_ACTIVE_CONNECTIONS

        assert isinstance(WS_ACTIVE_CONNECTIONS, Gauge)
        WS_ACTIVE_CONNECTIONS.inc()
        WS_ACTIVE_CONNECTIONS.dec()

    def test_ws_messages_sent_is_counter(self):
        from backend.core.metrics import WS_MESSAGES_SENT

        assert isinstance(WS_MESSAGES_SENT, Counter)
        WS_MESSAGES_SENT.labels(type="quote").inc()

    def test_ws_messages_dropped_is_counter(self):
        from backend.core.metrics import WS_MESSAGES_DROPPED

        assert isinstance(WS_MESSAGES_DROPPED, Counter)
        WS_MESSAGES_DROPPED.inc(5)

    def test_ws_subscriptions_is_gauge(self):
        from backend.core.metrics import WS_SUBSCRIPTIONS

        assert isinstance(WS_SUBSCRIPTIONS, Gauge)
        WS_SUBSCRIPTIONS.set(10)


class TestRedisMetrics:
    """Redis 指标测试"""

    def test_redis_queue_depth_is_gauge(self):
        from backend.core.metrics import REDIS_QUEUE_DEPTH

        assert isinstance(REDIS_QUEUE_DEPTH, Gauge)
        REDIS_QUEUE_DEPTH.labels(queue="quant:quotes:stream").set(100)

    def test_redis_operation_latency_is_summary(self):
        from backend.core.metrics import REDIS_OPERATION_LATENCY

        assert isinstance(REDIS_OPERATION_LATENCY, Summary)
        REDIS_OPERATION_LATENCY.labels(operation="hset").observe(0.001)

    def test_redis_errors_is_counter(self):
        from backend.core.metrics import REDIS_ERRORS

        assert isinstance(REDIS_ERRORS, Counter)
        REDIS_ERRORS.labels(operation="publish").inc()


class TestCircuitBreakerMetrics:
    """熔断器指标测试"""

    def test_circuit_breaker_state_is_gauge(self):
        from backend.core.metrics import CIRCUIT_BREAKER_STATE

        assert isinstance(CIRCUIT_BREAKER_STATE, Gauge)
        CIRCUIT_BREAKER_STATE.labels(service="futu").set(0)

    def test_circuit_breaker_transitions_is_counter(self):
        from backend.core.metrics import CIRCUIT_BREAKER_TRANSITIONS

        assert isinstance(CIRCUIT_BREAKER_TRANSITIONS, Counter)
        CIRCUIT_BREAKER_TRANSITIONS.labels(
            service="futu", from_state="closed", to_state="open"
        ).inc()


class TestAgentAndClientMetrics:
    """Agent / LLM / 客户端 APM 指标测试"""

    def test_client_heartbeat_total_is_counter(self):
        from backend.core.metrics import CLIENT_HEARTBEAT_TOTAL

        assert isinstance(CLIENT_HEARTBEAT_TOTAL, Counter)
        CLIENT_HEARTBEAT_TOTAL.labels(platform="web").inc()

    def test_llm_request_latency_is_histogram(self):
        from backend.core.metrics import LLM_REQUEST_LATENCY

        assert isinstance(LLM_REQUEST_LATENCY, Histogram)
        LLM_REQUEST_LATENCY.labels(model="gpt-4").observe(1.5)

    def test_llm_token_usage_is_counter(self):
        from backend.core.metrics import LLM_TOKEN_USAGE

        assert isinstance(LLM_TOKEN_USAGE, Counter)
        LLM_TOKEN_USAGE.labels(model="gpt-4", type="prompt").inc(500)

    def test_agent_tool_calls_is_counter(self):
        from backend.core.metrics import AGENT_TOOL_CALLS

        assert isinstance(AGENT_TOOL_CALLS, Counter)
        AGENT_TOOL_CALLS.labels(tool="get_quote", status="success").inc()


class TestFutuMetrics:
    """Futu OpenD 连接指标测试"""

    def test_futu_connection_status_is_gauge(self):
        from backend.core.metrics import FUTU_CONNECTION_STATUS

        assert isinstance(FUTU_CONNECTION_STATUS, Gauge)
        FUTU_CONNECTION_STATUS.set(1)

    def test_futu_reconnect_total_is_counter(self):
        from backend.core.metrics import FUTU_RECONNECT_TOTAL

        assert isinstance(FUTU_RECONNECT_TOTAL, Counter)
        FUTU_RECONNECT_TOTAL.inc()

    def test_futu_reconnect_failures_is_counter(self):
        from backend.core.metrics import FUTU_RECONNECT_FAILURES

        assert isinstance(FUTU_RECONNECT_FAILURES, Counter)
        FUTU_RECONNECT_FAILURES.inc()

    def test_futu_reconnect_latency_is_histogram(self):
        from backend.core.metrics import FUTU_RECONNECT_LATENCY

        assert isinstance(FUTU_RECONNECT_LATENCY, Histogram)
        FUTU_RECONNECT_LATENCY.observe(5.0)


class TestKlineCacheMetrics:
    """K线缓存命中指标测试"""

    def test_kline_cache_hit_is_counter(self):
        from backend.core.metrics import KLINE_CACHE_HIT

        assert isinstance(KLINE_CACHE_HIT, Counter)
        KLINE_CACHE_HIT.labels(tier="redis").inc()

    def test_kline_cache_query_latency_is_histogram(self):
        from backend.core.metrics import KLINE_CACHE_QUERY_LATENCY

        assert isinstance(KLINE_CACHE_QUERY_LATENCY, Histogram)
        KLINE_CACHE_QUERY_LATENCY.labels(tier="parquet").observe(0.01)


class TestDataQualityMetrics:
    """数据质量指标测试"""

    def test_market_data_correction_total_is_counter(self):
        from backend.core.metrics import MARKET_DATA_CORRECTION_TOTAL

        assert isinstance(MARKET_DATA_CORRECTION_TOTAL, Counter)
        MARKET_DATA_CORRECTION_TOTAL.labels(
            symbol="US.AAPL", check_type="quality_check"
        ).inc()

    def test_market_data_anomaly_total_is_counter(self):
        from backend.core.metrics import MARKET_DATA_ANOMALY_TOTAL

        assert isinstance(MARKET_DATA_ANOMALY_TOTAL, Counter)
        MARKET_DATA_ANOMALY_TOTAL.labels(symbol="HK.00700", severity="critical").inc()


class TestMetricsRegistryIntegration:
    """指标注册到全局 REGISTRY 的集成验证"""

    def test_all_metrics_registered(self):
        # 验证所有 metric 对象都在 REGISTRY 中可被采集
        # 注意: Counter 类型在 prometheus_client 中存储时会自动去除 "_total" 后缀
        names_to_check = [
            "quant_market_quote_latency_seconds",
            "quant_market_quote_staleness_seconds",
            "quant_market_quote",
            "quant_ws_active_connections",
            "quant_redis_queue_depth",
            "quant_circuit_breaker_state",
            "quant_client_heartbeat",
            "quant_llm_request_seconds",
            "quant_futu_connection_status",
            "quant_kline_cache_hit",
            "quant_market_data_correction",
        ]
        registered_names = {m.name for m in REGISTRY.collect()}
        for name in names_to_check:
            assert name in registered_names, f"指标 {name} 未注册到 REGISTRY"

    def test_module_exports_all_expected_symbols(self):
        from backend.core import metrics as metrics_module

        expected_attrs = [
            "MARKET_QUOTE_LATENCY",
            "MARKET_QUOTE_STALENESS",
            "MARKET_QUOTE_TOTAL",
            "WS_ACTIVE_CONNECTIONS",
            "WS_MESSAGES_SENT",
            "REDIS_QUEUE_DEPTH",
            "CIRCUIT_BREAKER_STATE",
            "FUTU_CONNECTION_STATUS",
            "KLINE_CACHE_HIT",
            "MARKET_DATA_CORRECTION_TOTAL",
        ]
        for attr in expected_attrs:
            assert hasattr(metrics_module, attr), f"metrics 模块缺少导出: {attr}"
