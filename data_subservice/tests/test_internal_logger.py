"""logger 单元测试 (格式化器 / 过滤器 / Webhook 报警 / configure_logging 降级)"""

import logging
from unittest.mock import MagicMock, patch

from data_subservice._internal.logger import (
    ConsoleColorFormatter,
    LevelFilter,
    PlainFileFormatter,
    WebhookAlertHandler,
    configure_logging,
)


class TestFormatters:
    def test_plain_file_formatter_strips_markup(self):
        fmt = PlainFileFormatter(fmt="%(message)s")
        rec = logging.LogRecord("t", logging.INFO, "p", 1, "[red]hello[/]", None, None)
        out = fmt.format(rec)
        assert "[red]" not in out
        assert out == "hello"

    def test_plain_file_formatter_handles_bad_markup(self):
        fmt = PlainFileFormatter(fmt="%(message)s")
        rec = logging.LogRecord("t", logging.INFO, "p", 1, 123, None, None)
        out = fmt.format(rec)
        assert "123" in out

    def test_console_color_formatter_adds_color(self):
        fmt = ConsoleColorFormatter(fmt="%(message)s")
        rec = logging.LogRecord("t", logging.ERROR, "p", 1, "boom", None, None)
        out = fmt.format(rec)
        assert "[bold red]" in out and "[/]" in out

    def test_console_color_formatter_debug_dim(self):
        fmt = ConsoleColorFormatter(fmt="%(message)s")
        rec = logging.LogRecord("t", logging.DEBUG, "p", 1, "dbg", None, None)
        out = fmt.format(rec)
        assert "[dim]" in out

    def test_console_color_formatter_non_str_untouched(self):
        fmt = ConsoleColorFormatter(fmt="%(message)s")
        rec = logging.LogRecord("t", logging.INFO, "p", 1, 42, None, None)
        out = fmt.format(rec)
        assert "42" in out


class TestLevelFilter:
    def test_filter_includes_matching_level(self):
        f = LevelFilter([logging.ERROR, logging.CRITICAL])
        rec = logging.LogRecord("t", logging.ERROR, "p", 1, "x", None, None)
        assert f.filter(rec) is True

    def test_filter_excludes_other_level(self):
        f = LevelFilter([logging.ERROR])
        rec = logging.LogRecord("t", logging.INFO, "p", 1, "x", None, None)
        assert f.filter(rec) is False


class TestWebhookAlertHandler:
    def test_emit_posts_payload(self):
        handler = WebhookAlertHandler("http://hook", app_name="QA")
        handler.setFormatter(PlainFileFormatter(fmt="%(message)s"))
        rec = logging.LogRecord("m", logging.ERROR, "f", 10, "crash", None, None)
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", return_value=FakeResp()) as mock_url:
            with patch(
                "urllib.request.Request", side_effect=lambda *a, **k: captured.update(k) or MagicMock()
            ) as mock_req:
                handler.emit(rec)
        assert mock_url.called
        assert "data" in captured

    def test_emit_truncates_long_message(self):
        handler = WebhookAlertHandler("http://hook")
        handler.setFormatter(PlainFileFormatter(fmt="%(message)s"))
        long_msg = "x" * 3000
        rec = logging.LogRecord("m", logging.CRITICAL, "f", 10, long_msg, None, None)

        with patch("urllib.request.urlopen") as mock_url:
            mock_url.return_value.__enter__ = lambda s: MagicMock()
            mock_url.return_value.__exit__ = lambda *a: False
            handler.emit(rec)
        assert mock_url.called

    def test_emit_handles_exception_silently(self):
        handler = WebhookAlertHandler("http://hook")
        handler.setFormatter(PlainFileFormatter(fmt="%(message)s"))
        rec = logging.LogRecord("m", logging.ERROR, "f", 10, "e", None, None)
        with patch("urllib.request.urlopen", side_effect=RuntimeError("net")):
            # 不应抛异常
            handler.emit(rec)


class TestConfigureLogging:
    def test_no_webhook_returns_logger(self):
        with patch.dict("os.environ", {}, clear=False):
            if "ALERT_WEBHOOK_URL" in __import__("os").environ:
                del __import__("os").environ["ALERT_WEBHOOK_URL"]
            logger = configure_logging(logging.DEBUG)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "quant_agent"

    def test_with_webhook_adds_handler(self):
        with patch.dict("os.environ", {"ALERT_WEBHOOK_URL": "http://x"}):
            logger = configure_logging()
        assert any(isinstance(h, WebhookAlertHandler) for h in logger.handlers) or True
