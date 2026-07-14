"""
Quant Agent OpenTelemetry 配置 (BE-10)

功能：
- 所有 API 请求自动注入标准 OTEL trace_id (32-char hex)
- 支持 W3C Trace Context 传播（上游网关透传）
- trace_id 写入 response header X-Trace-Id + structlog
- 可选导出到 OTLP（Grafana Tempo / 云 APM）

环境变量：
- OTEL_ENABLED: 是否启用 (默认 true)
- OTEL_SERVICE_NAME: 服务名 (默认 quant-agent)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP HTTP 地址
  (默认 http://localhost:4318/v1/traces；设 none 则 Console)
- OTEL_SAMPLING_RATE: 采样率 0.0–1.0 (默认 1.0)
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
#  可选依赖
# ─────────────────────────────────────────
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace import Span, Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    trace = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]
    TracerProvider = None  # type: ignore[assignment]
    BatchSpanProcessor = None  # type: ignore[assignment]
    ConsoleSpanExporter = None  # type: ignore[assignment]
    ParentBased = None  # type: ignore[assignment]
    TraceIdRatioBased = None  # type: ignore[assignment]
    Span = None  # type: ignore[assignment]
    Status = None  # type: ignore[assignment]
    StatusCode = None  # type: ignore[assignment]
    _OTEL_AVAILABLE = False

OTLPSpanExporter = None
FastAPIInstrumentor = None
LoggingInstrumentor = None
RedisInstrumentor = None
RequestsInstrumentor = None
HTTPXClientInstrumentor = None
SQLAlchemyInstrumentor = None

if _OTEL_AVAILABLE:
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as _OTLP,
        )

        OTLPSpanExporter = _OTLP
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor as _FI

        FastAPIInstrumentor = _FI
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor as _LI

        LoggingInstrumentor = _LI
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor as _RI

        RedisInstrumentor = _RI
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor as _Req

        RequestsInstrumentor = _Req
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor as _HX

        HTTPXClientInstrumentor = _HX
    except ImportError:
        pass
    try:
        from opentelemetry.instrumentation.sqlalchemy import (
            SQLAlchemyInstrumentor as _SA,
        )

        SQLAlchemyInstrumentor = _SA
    except ImportError:
        pass

# ─────────────────────────────────────────
#  配置
# ─────────────────────────────────────────
OTEL_ENABLED = os.getenv("OTEL_ENABLED", "true").lower() == "true"
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "quant-agent")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
try:
    OTEL_SAMPLING_RATE = float(os.getenv("OTEL_SAMPLING_RATE", "1.0"))
except ValueError:
    OTEL_SAMPLING_RATE = 1.0
OTEL_SAMPLING_RATE = max(0.0, min(1.0, OTEL_SAMPLING_RATE))

_tracer: Any = None
_initialized = False


def is_otel_ready() -> bool:
    return bool(_OTEL_AVAILABLE and OTEL_ENABLED and _initialized)


def get_tracer() -> Any:
    """获取全局 Tracer；OTEL 不可用时返回 NoOp 兼容桩。"""
    global _tracer
    if not _OTEL_AVAILABLE or trace is None:
        return _NoopTracer()
    if _tracer is None:
        _tracer = trace.get_tracer(OTEL_SERVICE_NAME, "1.0.0")
    return _tracer


def get_current_trace_id() -> str:
    """当前 OTEL trace_id（32-char hex）；无 span 时返回空串。"""
    if not _OTEL_AVAILABLE or trace is None:
        return ""
    try:
        span = trace.get_current_span()
        if span is None:
            return ""
        ctx = span.get_span_context()
        if ctx is None or not getattr(ctx, "is_valid", True):
            return ""
        # NonRecordingSpan 也可能有有效 context（来自上游透传）
        tid = getattr(ctx, "trace_id", 0) or 0
        if tid == 0:
            return ""
        return format(tid, "032x")
    except Exception:
        return ""


def get_current_span_id() -> str:
    if not _OTEL_AVAILABLE or trace is None:
        return ""
    try:
        span = trace.get_current_span()
        if span is None:
            return ""
        ctx = span.get_span_context()
        sid = getattr(ctx, "span_id", 0) or 0
        if sid == 0:
            return ""
        return format(sid, "016x")
    except Exception:
        return ""


class _NoopSpan:
    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        return None

    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        return None

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


class _NoopTracer:
    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


@contextmanager
def traced_span(name: str, attributes: Optional[dict] = None) -> Generator[Any, None, None]:
    """业务代码子 span；OTEL 关闭时为 no-op。"""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes and hasattr(span, "set_attribute"):
            for k, v in attributes.items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    pass
        yield span


def set_span_error(span: Any, exc: Exception) -> None:
    if span is None or Status is None or StatusCode is None:
        return
    try:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        span.record_exception(exc)
    except Exception:
        pass


def init_otel(app: Any = None) -> None:
    """初始化 TracerProvider 并挂载自动埋点（应在 FastAPI 创建后尽早调用）。"""
    global _tracer, _initialized

    if not _OTEL_AVAILABLE:
        logger.warning("otel_sdk_missing skip_init")
        return

    if not OTEL_ENABLED:
        logger.info("otel_disabled skip_init")
        return

    if _initialized:
        logger.debug("otel_already_initialized")
        return

    resource = Resource.create(
        {
            "service.name": OTEL_SERVICE_NAME,
            "service.version": os.getenv("QUANT_VERSION", "0.1.0"),
            "deployment.environment": os.getenv("QUANT_ENV", "development"),
        }
    )

    sampler = ParentBased(TraceIdRatioBased(OTEL_SAMPLING_RATE))
    provider = TracerProvider(resource=resource, sampler=sampler)

    endpoint = (OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()
    if endpoint and endpoint.lower() != "none" and OTLPSpanExporter is not None:
        exporter: Any = OTLPSpanExporter(endpoint=endpoint)
        logger.info("otel_exporter_otlp endpoint=%s", endpoint)
    else:
        exporter = ConsoleSpanExporter()
        logger.info("otel_exporter_console")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(OTEL_SERVICE_NAME, "1.0.0")

    if app is not None and FastAPIInstrumentor is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        logger.info("otel_fastapi_instrumented")

    if LoggingInstrumentor is not None:
        LoggingInstrumentor().instrument(set_logging_format=True)
        logger.info("otel_logging_instrumented")

    if RedisInstrumentor is not None:
        try:
            RedisInstrumentor().instrument()
            logger.info("otel_redis_instrumented")
        except Exception as e:
            logger.warning("otel_redis_instrument_failed err=%s", e)

    if RequestsInstrumentor is not None:
        try:
            RequestsInstrumentor().instrument()
            logger.info("otel_requests_instrumented")
        except Exception as e:
            logger.warning("otel_requests_instrument_failed err=%s", e)

    if HTTPXClientInstrumentor is not None:
        try:
            HTTPXClientInstrumentor().instrument()
            logger.info("otel_httpx_instrumented")
        except Exception as e:
            logger.warning("otel_httpx_instrument_failed err=%s", e)

    if SQLAlchemyInstrumentor is not None:
        try:
            from backend.core.database import engine as sa_engine

            SQLAlchemyInstrumentor().instrument(engine=sa_engine)
            logger.info("otel_sqlalchemy_instrumented")
        except Exception as e:
            logger.warning("otel_sqlalchemy_instrument_failed err=%s", e)

    _initialized = True
    logger.info(
        "otel_ready service=%s sample_rate=%s",
        OTEL_SERVICE_NAME,
        OTEL_SAMPLING_RATE,
    )


def shutdown_otel() -> None:
    if not _OTEL_AVAILABLE or trace is None:
        return
    try:
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception as e:
        logger.warning("otel_shutdown_failed err=%s", e)
