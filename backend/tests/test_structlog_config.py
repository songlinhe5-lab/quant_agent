"""
structlog 结构化日志配置单元测试
覆盖: backend/core/structlog_config.py
"""

import logging
import os
import sys
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("EMBEDDING_API_KEY", "test-key")
os.environ.setdefault("EMBEDDING_BASE_URL", "https://api.test.com")
os.environ.setdefault("INTERNAL_API_SECRET", "test-secret-key")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))


class TestNewTraceId:
    """trace_id 生成测试"""

    def test_new_trace_id_returns_16_char_hex(self):
        from backend.core.structlog_config import new_trace_id

        tid = new_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 16
        # 验证 hex 字符
        int(tid, 16)

    def test_new_trace_id_is_unique(self):
        from backend.core.structlog_config import new_trace_id

        ids = {new_trace_id() for _ in range(100)}
        assert len(ids) >= 95  # 极小概率重复


class TestContextVars:
    """contextvars 上下文变量测试"""

    def test_trace_id_var_default(self):
        from backend.core.structlog_config import trace_id_var

        assert trace_id_var.get() == "-"

    def test_symbol_var_default(self):
        from backend.core.structlog_config import symbol_var

        assert symbol_var.get() == "-"

    def test_latency_ms_var_default(self):
        from backend.core.structlog_config import latency_ms_var

        assert latency_ms_var.get() == 0.0


class TestInjectContextVars:
    """inject_context_vars 处理器测试"""

    def test_inject_default_values(self):
        from backend.core.structlog_config import inject_context_vars

        event_dict = {"event": "test"}
        result = inject_context_vars(None, "info", event_dict)
        assert result["trace_id"] == "-"
        assert result["symbol"] == "-"
        # latency_ms 默认 0 不应被注入
        assert "latency_ms" not in result

    def test_inject_with_custom_context(self):
        from backend.core.structlog_config import (
            inject_context_vars,
            latency_ms_var,
            symbol_var,
            trace_id_var,
        )

        trace_id_var.set("abc-123")
        symbol_var.set("US.AAPL")
        latency_ms_var.set(12.345)

        event_dict = {"event": "quote"}
        result = inject_context_vars(None, "info", event_dict)
        assert result["trace_id"] == "abc-123"
        assert result["symbol"] == "US.AAPL"
        assert result["latency_ms"] == 12.35  # 保留 2 位小数

    def test_inject_preserves_existing_keys(self):
        from backend.core.structlog_config import inject_context_vars, trace_id_var

        trace_id_var.set("auto-set")
        event_dict = {"event": "msg", "trace_id": "predefined"}
        result = inject_context_vars(None, "info", event_dict)
        # setdefault 不覆盖已有值
        assert result["trace_id"] == "predefined"


class TestDropColorForJson:
    """drop_color_for_json 处理器测试"""

    def test_strip_rich_markup(self):
        from backend.core.structlog_config import drop_color_for_json

        event_dict = {"event": "[green]success[/green] message"}
        result = drop_color_for_json(None, "info", event_dict)
        assert "[" not in result["event"]
        assert "success" in result["event"]
        assert "message" in result["event"]

    def test_skip_non_string_message(self):
        from backend.core.structlog_config import drop_color_for_json

        event_dict = {"event": 12345}
        result = drop_color_for_json(None, "info", event_dict)
        assert result["event"] == 12345

    def test_skip_message_without_brackets(self):
        from backend.core.structlog_config import drop_color_for_json

        event_dict = {"event": "plain message"}
        result = drop_color_for_json(None, "info", event_dict)
        assert result["event"] == "plain message"


class TestOrderFields:
    """order_fields 处理器测试"""

    def test_order_basic_fields_first(self):
        from backend.core.structlog_config import order_fields

        event_dict = {
            "extra_field": "value",
            "event": "test event",
            "trace_id": "abc",
            "level": "info",
            "symbol": "US.AAPL",
            "timestamp": "2024-01-01",
            "latency_ms": 1.5,
        }
        result = order_fields(None, "info", event_dict)
        keys = list(result.keys())
        # 关键字段应排在前面
        assert keys[0] == "timestamp"
        assert keys[1] == "level"
        assert keys[2] == "event"
        assert keys[3] == "trace_id"
        assert keys[4] == "symbol"
        assert keys[5] == "latency_ms"
        assert "extra_field" in result

    def test_order_with_missing_keys(self):
        from backend.core.structlog_config import order_fields

        event_dict = {"event": "test", "other": "val"}
        result = order_fields(None, "info", event_dict)
        assert list(result.keys())[0] == "event"
        assert result["other"] == "val"


class TestStructlogJsonFormatter:
    """StructlogJsonFormatter 测试"""

    def test_format_json_message_passthrough(self):
        from backend.core.structlog_config import StructlogJsonFormatter

        formatter = StructlogJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='{"event": "already json", "level": "INFO"}',
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        assert result.startswith("{")
        import json as _json

        parsed = _json.loads(result)
        assert parsed["event"] == "already json"

    def test_format_wraps_plain_message(self):
        from backend.core.structlog_config import StructlogJsonFormatter

        formatter = StructlogJsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="plain warning message",
            args=(),
            exc_info=None,
        )
        result = formatter.format(record)
        import json as _json

        parsed = _json.loads(result)
        assert parsed["event"] == "plain warning message"
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "test_logger"
        assert "timestamp" in parsed

    def test_format_with_extra_fields(self):
        from backend.core.structlog_config import StructlogJsonFormatter

        formatter = StructlogJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="msg with extras",
            args=(),
            exc_info=None,
        )
        record.trace_id = "trace-xyz"
        record.symbol = "HK.00700"
        # latency_ms 默认为 "-" 不应被加入
        result = formatter.format(record)
        import json as _json

        parsed = _json.loads(result)
        assert parsed["trace_id"] == "trace-xyz"
        assert parsed["symbol"] == "HK.00700"
        assert "latency_ms" not in parsed


class TestConfigureStructlog:
    """configure_structlog 配置入口测试"""

    def test_configure_is_idempotent(self):
        from backend.core import structlog_config

        # 第一次调用应执行配置（可能已在其他测试中调用过）
        structlog_config.configure_structlog()
        # 重置 _configured 标志后再次调用
        structlog_config._configured = False
        structlog_config.configure_structlog()
        # 第二次调用应被忽略
        assert structlog_config._configured is True

    def test_configure_dev_mode(self):
        from backend.core import structlog_config

        with patch.dict(os.environ, {"QUANT_ENV": "development"}):
            structlog_config._configured = False
            structlog_config.configure_structlog()
            assert structlog_config._configured is True

    def test_configure_prod_mode(self):
        from backend.core import structlog_config

        with patch.dict(os.environ, {"QUANT_ENV": "production"}):
            structlog_config._configured = False
            structlog_config.configure_structlog()
            assert structlog_config._configured is True


class TestGetLogger:
    """get_logger 便捷 API 测试"""

    def test_get_logger_returns_bound_logger(self):
        from backend.core.structlog_config import get_logger

        log = get_logger("test_module")
        assert log is not None
        # 应支持标准日志方法
        assert hasattr(log, "info")
        assert hasattr(log, "error")
        assert hasattr(log, "debug")

    def test_get_logger_default_name(self):
        from backend.core.structlog_config import get_logger

        log = get_logger()
        assert log is not None

    def test_get_logger_can_emit(self):
        from backend.core.structlog_config import get_logger

        log = get_logger("emit_test")
        # 仅验证不抛异常
        log.info("test info message")
        log.error("test error message")


class TestBindContext:
    """bind_context 便捷 API 测试"""

    def test_bind_trace_id(self):
        from backend.core.structlog_config import bind_context, trace_id_var

        bind_context(trace_id="custom-trace-001")
        assert trace_id_var.get() == "custom-trace-001"

    def test_bind_symbol(self):
        from backend.core.structlog_config import bind_context, symbol_var

        bind_context(symbol="US.TSLA")
        assert symbol_var.get() == "US.TSLA"

    def test_bind_latency_ms(self):
        from backend.core.structlog_config import bind_context, latency_ms_var

        bind_context(latency_ms=42.5)
        assert latency_ms_var.get() == 42.5

    def test_bind_unknown_key_is_ignored(self):
        from backend.core.structlog_config import bind_context

        # 未知 key 应被静默忽略，不抛异常
        bind_context(unknown_field="value")
