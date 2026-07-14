"""BE-10: OpenTelemetry 配置与 API X-Trace-Id 注入。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


class TestOtelConfigDisabled:
    """OTEL 关闭或 SDK 缺失时的安全退化。"""

    def test_get_current_trace_id_empty_when_unavailable(self):
        with patch("backend.core.otel_config._OTEL_AVAILABLE", False):
            with patch("backend.core.otel_config.trace", None):
                from backend.core import otel_config as oc

                assert oc.get_current_trace_id() == ""

    def test_get_current_span_id_empty_when_unavailable(self):
        with patch("backend.core.otel_config._OTEL_AVAILABLE", False):
            with patch("backend.core.otel_config.trace", None):
                from backend.core import otel_config as oc

                assert oc.get_current_span_id() == ""

    def test_traced_span_noop_when_unavailable(self):
        with patch("backend.core.otel_config._OTEL_AVAILABLE", False):
            with patch("backend.core.otel_config.trace", None):
                from backend.core.otel_config import traced_span

                with traced_span("unit-test", {"k": "v"}) as span:
                    assert span is not None
                    span.set_attribute("x", 1)

    def test_init_otel_skips_when_disabled(self):
        with patch("backend.core.otel_config.OTEL_ENABLED", False):
            with patch("backend.core.otel_config._OTEL_AVAILABLE", True):
                with patch("backend.core.otel_config._initialized", False):
                    from backend.core.otel_config import init_otel
                    from backend.core import otel_config as oc

                    init_otel(app=None)
                    assert oc._initialized is False

    def test_shutdown_otel_safe_when_unavailable(self):
        with patch("backend.core.otel_config._OTEL_AVAILABLE", False):
            with patch("backend.core.otel_config.trace", None):
                from backend.core.otel_config import shutdown_otel

                shutdown_otel()


class TestOtelTraceIdFromSpan:
    def test_formats_valid_trace_id(self):
        from backend.core import otel_config as oc

        if not oc._OTEL_AVAILABLE:
            pytest.skip("opentelemetry not installed")

        mock_ctx = MagicMock()
        mock_ctx.is_valid = True
        mock_ctx.trace_id = 0xABCDEF0123456789ABCDEF0123456789

        mock_span = MagicMock()
        mock_span.get_span_context.return_value = mock_ctx

        with patch.object(oc.trace, "get_current_span", return_value=mock_span):
            tid = oc.get_current_trace_id()
        assert tid == "abcdef0123456789abcdef0123456789"
        assert len(tid) == 32

    def test_zero_trace_id_returns_empty(self):
        from backend.core import otel_config as oc

        if not oc._OTEL_AVAILABLE:
            pytest.skip("opentelemetry not installed")

        mock_ctx = MagicMock()
        mock_ctx.is_valid = True
        mock_ctx.trace_id = 0
        mock_span = MagicMock()
        mock_span.get_span_context.return_value = mock_ctx

        with patch.object(oc.trace, "get_current_span", return_value=mock_span):
            assert oc.get_current_trace_id() == ""


class TestTraceIdMiddlewareContract:
    """镜像 main.trace_id_middleware：响应必须带回 X-Trace-Id。"""

    @pytest.fixture
    def mini_client(self):
        from backend.core.otel_config import get_current_trace_id
        from backend.core.structlog_config import new_trace_id, trace_id_var

        app = FastAPI()

        @app.middleware("http")
        async def trace_id_middleware(request: Request, call_next):
            otel_tid = get_current_trace_id()
            if not otel_tid:
                otel_tid = request.headers.get("x-trace-id", new_trace_id())
            token = trace_id_var.set(otel_tid)
            try:
                response = await call_next(request)
                otel_tid = get_current_trace_id() or otel_tid
                response.headers["X-Trace-Id"] = otel_tid
                return response
            finally:
                trace_id_var.reset(token)

        @app.get("/ping")
        async def ping():
            return {"ok": True}

        return TestClient(app)

    def test_response_has_x_trace_id(self, mini_client):
        resp = mini_client.get("/ping")
        assert resp.status_code == 200
        tid = resp.headers.get("X-Trace-Id")
        assert tid
        assert tid != "-"
        assert len(tid) >= 8

    def test_client_x_trace_id_echoed_when_otel_empty(self, mini_client):
        with patch("backend.core.otel_config.get_current_trace_id", return_value=""):
            resp = mini_client.get(
                "/ping",
                headers={"X-Trace-Id": "client-trace-be10-001"},
            )
        assert resp.status_code == 200
        assert resp.headers.get("X-Trace-Id") == "client-trace-be10-001"


class TestSetSpanError:
    def test_set_span_error_noop_without_status(self):
        from backend.core.otel_config import set_span_error

        with patch("backend.core.otel_config.Status", None):
            set_span_error(MagicMock(), RuntimeError("boom"))
