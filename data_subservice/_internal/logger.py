"""Quant Agent 日志系统（复制自 backend.core.logger，物理解耦，零 backend 依赖）

自包含：仅依赖 rich / logging 标准库，不 import 任何 backend 内部模块。
"""

import atexit
import json
import logging
import os
import urllib.request
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from queue import Queue

from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

custom_theme = Theme(
    {
        "logging.level.debug": "dim white",
        "logging.level.info": "bold cyan",
        "logging.level.warning": "bold yellow",
        "logging.level.error": "bold red",
        "logging.level.critical": "bold white on red",
    }
)

console = Console(theme=custom_theme)


class PlainFileFormatter(logging.Formatter):
    """用于剥离 Rich [color] 标签的纯文本格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        try:
            clean_msg = Text.from_markup(record.getMessage()).plain
        except Exception:
            clean_msg = record.getMessage()

        original_msg = record.msg
        original_args = record.args

        record.msg = clean_msg
        record.args = None
        result = super().format(record)

        record.msg = original_msg
        record.args = original_args
        return result


class ConsoleColorFormatter(logging.Formatter):
    """用于在终端为不同级别的日志正文内容增加全身颜色高亮"""

    LEVEL_COLORS = {
        logging.DEBUG: "dim",
        logging.INFO: "cyan",
        logging.WARNING: "bold yellow",
        logging.ERROR: "bold red",
        logging.CRITICAL: "bold white on red",
    }

    def format(self, record: logging.LogRecord) -> str:
        original_msg = record.msg
        color = self.LEVEL_COLORS.get(record.levelno, "")

        if color and isinstance(record.msg, str):
            record.msg = f"[{color}]{record.msg}[/]"

        result = super().format(record)
        record.msg = original_msg
        return result


class LevelFilter(logging.Filter):
    """用于精确过滤特定日志级别的过滤器"""

    def __init__(self, levels):
        super().__init__()
        self.levels = levels

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno in self.levels


class WebhookAlertHandler(logging.Handler):
    """用于严重错误报警的 Webhook 处理器 (钉钉/企微/Telegram)"""

    def __init__(self, webhook_url: str, app_name: str = "Quant Agent"):
        super().__init__()
        self.webhook_url = webhook_url
        self.app_name = app_name

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)

            if len(msg) > 2000:
                msg = msg[:2000] + "\n...[Truncated: 去日志文件查看完整追踪]"

            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"🚨 [{self.app_name} 异常熔断]\n级别: {record.levelname}\n位置: {record.module}.{record.funcName}\n详情:\n{msg}"  # noqa: E501
                },
            }

            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """配置全局优雅且无阻塞异步持久化的日志系统"""
    console_handler = RichHandler(rich_tracebacks=True, tracebacks_show_locals=True, markup=True, console=console)
    console_handler.setFormatter(ConsoleColorFormatter(fmt="%(message)s"))

    os.makedirs("logs", exist_ok=True)

    file_formatter = PlainFileFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    def _create_file_handler(filename: str, levels: list) -> TimedRotatingFileHandler:
        handler = TimedRotatingFileHandler(
            filename,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(file_formatter)
        handler.addFilter(LevelFilter(levels))
        return handler

    debug_handler = _create_file_handler("logs/debug.log", [logging.DEBUG])
    info_handler = _create_file_handler("logs/info.log", [logging.INFO])
    warning_handler = _create_file_handler("logs/warning.log", [logging.WARNING])
    error_handler = _create_file_handler("logs/error.log", [logging.ERROR, logging.CRITICAL])

    handlers_for_listener = [
        console_handler,
        debug_handler,
        info_handler,
        warning_handler,
        error_handler,
    ]

    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if webhook_url:
        webhook_handler = WebhookAlertHandler(webhook_url)
        webhook_handler.setLevel(logging.ERROR)
        webhook_handler.setFormatter(PlainFileFormatter(fmt="%(message)s"))
        handlers_for_listener.append(webhook_handler)

    log_queue = Queue(-1)
    queue_handler = QueueHandler(log_queue)

    listener = QueueListener(log_queue, *handlers_for_listener, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)

    logging.basicConfig(level=level, handlers=[queue_handler])

    logger = logging.getLogger("quant_agent")

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return logger


# 导出一个单例 logger 供全局直接导入使用
logger = configure_logging()


__all__ = ["logger", "configure_logging"]
