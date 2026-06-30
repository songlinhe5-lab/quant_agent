"""
Quant Agent OpenTelemetry 配置 (BE-10)

功能：
- 所有 API 请求自动注入标准 OTEL trace_id (32-char hex)
- 支持 W3C Trace Context 传播（上游网关透传）
- trace_id 同时写入 response header X-Trace-Id 和 structlog 日志
- 可选导出到 OTLP Collector (Grafana Tempo / 阿里云 ARMS / 腾讯云 APM)

环境变量：
- OTEL_ENABLED: 是否启用 OTEL (默认 true)
- OTEL_SERVICE_NAME: 服务名 (默认 quant-agent)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP 导出地址 (默认 http://localhost:4318/v1/traces)
- OTEL_SAMPLING_RATE: 采样率 0.0-1.0 (默认 1.0，全采样)
"""

import os
from contextlib import contextmanager
from typing import Optional

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, Status, StatusCode

# ─────────────────────────────────────────
#  配置读取
# ─────────────────────────────────────────
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() == "true"
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "quant-agent")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces"
)
OTEL_SAMPLING_RATE = float(os.getenv("OTEL_SAMPLING_RATE", "1.0"))

# ─────────────────────────────────────────
#  全局 Tracer
# ─────────────────────────────────────────
_tracer: Optional[trace.Tracer] = None


def get_tracer() -> trace.Tracer:
    """获取全局 Tracer 实例"""
    global _tracer
    if _tracer is None:
        _tracer = trace.get_tracer(OTEL_SERVICE_NAME, "1.0.0")
    return _tracer


def get_current_trace_id() -> str:
    """
    获取当前上下文的标准 OTEL trace_id (32-char hex小写)。
    如果不在 span 上下文中，返回空字符串。
    """
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return ""
    ctx = span.get_span_context()
    return format(ctx.trace_id, "032x")


def get_current_span_id() -> str:
    """获取当前上下文的 span_id (16-char hex小写)"""
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return ""
    ctx = span.get_span_context()
    return format(ctx.span_id, "016x")


@contextmanager
def traced_span(name: str, attributes: Optional[dict] = None):
    """
    便捷上下文管理器：在任意业务代码中创建子 span。

    用法：
        with traced_span("yfinance.fetch", {"symbol": "AAPL"}):
            data = yf.download("AAPL")
    """
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        yield span


def set_span_error(span: Span, exc: Exception) -> None:
    """标记 span 为错误状态"""
    span.set_status(Status(StatusCode.ERROR, str(exc)))
    span.record_exception(exc)


# ─────────────────────────────────────────
#  初始化 OTEL SDK
# ─────────────────────────────────────────
def init_otel(app=None) -> None:
    """
    初始化 OpenTelemetry TracerProvider 并挂载自动埋点。

    应在 FastAPI 启动前调用。
    如果传入 app，会自动挂载 FastAPIInstrumentor。
    """
    if not OTEL_ENABLED:
        print("ℹ️  [OTEL] OTEL_ENABLED=false，跳过初始化")
        return

    # 1. 创建 Resource (服务元数据)
    resource = Resource.create(
        attributes={
            "service.name": OTEL_SERVICE_NAME,
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("QUANT_ENV", "development"),
        }
    )

    # 2. 创建 TracerProvider
    provider = TracerProvider(resource=resource, sampler=None)  # 全采样

    # 3. 配置 Span 导出器
    otlp_endpoint = OTEL_EXPORTER_OTLP_ENDPOINT
    if otlp_endpoint and otlp_endpoint != "none":
        # 生产：导出到 OTLP Collector
        span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        print(f"✅ [OTEL] 已配置 OTLP 导出器: {otlp_endpoint}")
    else:
        # 开发：打印到控制台
        span_exporter = ConsoleSpanExporter()
        print("✅ [OTEL] 已配置 Console 导出器 (开发模式)")

    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)

    # 4. 自动埋点：FastAPI / Redis / requests / logging
    if app is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        print("✅ [OTEL] FastAPI 自动埋点已挂载")

    LoggingInstrumentor().instrument(set_logging_format=True)
    RedisInstrumentor().instrument()
    RequestsInstrumentor().instrument()
    print("✅ [OTEL] Redis / requests / logging 自动埋点已挂载")

    print(f"🚀 [OTEL] TracerProvider 初始化完成 (service={OTEL_SERVICE_NAME})")


def shutdown_otel() -> None:
    """优雅关闭 OTEL (清理导出器队列)"""
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
