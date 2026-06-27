"""
Quant Agent structlog 结构化日志配置（BE-05）

对齐 docs/08 可观测性规范：
- 所有日志必须携带 trace_id、symbol、latency_ms 字段
- 文件输出为 JSON 格式（便于 ELK/Loki 采集）
- 终端输出为彩色 key=value 格式（开发友好）

与现有 logger.py 的 QueueListener 体系完全兼容：
  structlog → 标准 logging → QueueHandler → QueueListener → Handlers
"""
import logging
import os
import sys
import uuid
import contextvars
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

# ─────────────────────────────────────────
#  上下文变量（跨协程/线程传播）
# ─────────────────────────────────────────
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
symbol_var: contextvars.ContextVar[str] = contextvars.ContextVar("symbol", default="-")
latency_ms_var: contextvars.ContextVar[float] = contextvars.ContextVar("latency_ms", default=0.0)


def new_trace_id() -> str:
    """生成一个短 trace_id（16 字符 hex）"""
    return uuid.uuid4().hex[:16]


# ─────────────────────────────────────────
#  structlog 处理器
# ─────────────────────────────────────────

def inject_context_vars(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """从 contextvars 注入 trace_id / symbol / latency_ms 到每条日志"""
    event_dict.setdefault("trace_id", trace_id_var.get("-"))
    event_dict.setdefault("symbol", symbol_var.get("-"))
    lm = latency_ms_var.get(0.0)
    if lm > 0:
        event_dict.setdefault("latency_ms", round(lm, 2))
    return event_dict


def drop_color_for_json(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """剥离 Rich markup 标签，确保 JSON 输出干净"""
    msg = event_dict.get("event", "")
    if isinstance(msg, str) and "[" in msg:
        try:
            from rich.text import Text
            event_dict["event"] = Text.from_markup(msg).plain
        except Exception:
            pass
    return event_dict


def order_fields(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """将关键字段排在前面，便于日志检索"""
    ordered: EventDict = {}
    for key in ("timestamp", "level", "event", "trace_id", "symbol", "latency_ms"):
        if key in event_dict:
            ordered[key] = event_dict.pop(key)
    ordered.update(event_dict)
    return ordered


# ─────────────────────────────────────────
#  JSON 文件 Formatter
# ─────────────────────────────────────────

class StructlogJsonFormatter(logging.Formatter):
    """将 structlog 事件序列化为 JSON 行（每行一条 JSON）"""

    def format(self, record: logging.LogRecord) -> str:
        import json as _json
        # structlog 已序列化的消息存储在 record.msg 中
        msg = record.getMessage()
        # 如果已经是 JSON 字符串，直接返回
        if msg.startswith("{"):
            return msg
        # 否则包装为 JSON
        data = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "event": msg,
            "logger": record.name,
        }
        # 附加 extra 字段
        for key in ("trace_id", "symbol", "latency_ms"):
            val = getattr(record, key, None)
            if val and val != "-":
                data[key] = val
        return _json.dumps(data, ensure_ascii=False)


# ─────────────────────────────────────────
#  配置入口
# ─────────────────────────────────────────

_configured = False


def configure_structlog(level: int = logging.INFO) -> None:
    """
    初始化 structlog，将其绑定到标准 logging 体系。

    仅在首次调用时生效（幂等）。
    应在 logger.py 的 configure_logging() 之后调用。
    """
    global _configured
    if _configured:
        return
    _configured = True

    is_dev = os.getenv("QUANT_ENV", "development") == "development"

    # 为文件 handler 挂载 JSON formatter
    quant_logger = logging.getLogger("quant_agent")
    for handler in quant_logger.handlers:
        if isinstance(handler, logging.handlers.QueueHandler):
            # QueueHandler 内部不直接设 formatter，而是由其 Listener 侧的 handler 控制
            pass

    # 遍历 QueueListener 的实际 handlers，为文件 handler 替换为 JSON formatter
    _patch_file_handlers_json()

    # 配置 structlog 的处理链
    shared_processors: list = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        inject_context_vars,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if is_dev:
        # 开发环境：彩色 key=value 控制台输出
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            pad_event=30,
        )
    else:
        # 生产环境：JSON 输出
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 配置 ProcessorFormatter 给 quant_agent logger
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            drop_color_for_json if not is_dev else lambda l, m, e: e,
            order_fields,
            renderer,
        ],
    )

    # 替换 quant_agent 的 root handler 的 formatter
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(formatter)


def _patch_file_handlers_json() -> None:
    """为日志文件 handler 切换为 JSON 格式"""
    import json as _json
    from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler

    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, QueueHandler):
            listener = getattr(handler, "listener", None)
            if listener is None:
                # Try to find the listener from the queue
                continue
            # 遍历 listener 的实际 handlers
            for lh in getattr(listener, "handlers", []):
                if isinstance(lh, TimedRotatingFileHandler):
                    lh.setFormatter(StructlogJsonFormatter())


# ─────────────────────────────────────────
#  便捷 API
# ─────────────────────────────────────────

def get_logger(name: str = "quant_agent") -> structlog.stdlib.BoundLogger:
    """获取 structlog 绑定日志器，自动携带当前上下文的 trace_id / symbol / latency_ms"""
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """
    向当前协程上下文绑定额外字段（如 symbol="US.AAPL"）。

    用法：
        from backend.core.structlog_config import bind_context
        bind_context(symbol="US.AAPL")
        get_logger().info("行情更新")  # 自动携带 symbol=US.AAPL
    """
    for key, value in kwargs.items():
        if key == "trace_id":
            trace_id_var.set(str(value))
        elif key == "symbol":
            symbol_var.set(str(value))
        elif key == "latency_ms":
            latency_ms_var.set(float(value))
