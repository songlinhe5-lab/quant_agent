import logging
import sys
import os
import json
import urllib.request
import atexit
from queue import Queue
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme

# 定义控制台不同级别的高亮主题 (针对日志级别标签 [INFO], [ERROR] 等)
custom_theme = Theme({
    "logging.level.debug": "dim white",
    "logging.level.info": "bold cyan",
    "logging.level.warning": "bold yellow",
    "logging.level.error": "bold red",
    "logging.level.critical": "bold white on red",
})

# 初始化 Rich 控制台，用于高级终端输出
console = Console(theme=custom_theme)

class PlainFileFormatter(logging.Formatter):
    """用于剥离 Rich [color] 标签的纯文本格式化器"""
    def format(self, record: logging.LogRecord) -> str:
        try:
            # 使用 Rich 原生解析器安全剥离如 [green] 这样的格式标签
            clean_msg = Text.from_markup(record.getMessage()).plain
        except Exception:
            clean_msg = record.getMessage()
            
        # 暂存原始记录（保护终端输出不受影响）
        original_msg = record.msg
        original_args = record.args
        
        # 替换为干净的文本供文件写入
        record.msg = clean_msg
        record.args = None
        result = super().format(record)
        
        # 恢复记录
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
            # 安全地包裹一层颜色，兼容已有的 rich markup，不影响 args 占位符解析
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
            # 格式化纯文本日志内容，并利用刚写的格式化器剥离颜色代码
            msg = self.format(record)
            
            # 截断过长的 Traceback，防止超出 Webhook 平台的字数限制
            if len(msg) > 2000:
                msg = msg[:2000] + "\n...[Truncated: 去日志文件查看完整追踪]"

            # 💡 此处以钉钉/企业微信机器人的 JSON 格式为例
            # 如果是 Telegram，只需修改 payload 结构为 {"chat_id": "你的ID", "text": "..."}
            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"🚨 [{self.app_name} 异常熔断]\n级别: {record.levelname}\n位置: {record.module}.{record.funcName}\n详情:\n{msg}"
                }
            }
            
            # 🛡️ 发送 HTTP 请求：因为运行在 QueueListener 的独立守护线程中，网络 I/O 绝对不会阻塞行情网关
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            # 降级兜底：坚决不能让报警本身的失败（如断网）引发日志线程崩溃
            pass

def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """
    配置全局优雅且无阻塞异步持久化的日志系统
    """
    # 1. 终端 Console Handler (高颜值呈现)
    console_handler = RichHandler(
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        markup=True,
        console=console
    )
    # 挂载正文颜色包裹器 (RichHandler 默认只提取 msg，因此格式设置为 %(message)s 即可)
    console_handler.setFormatter(ConsoleColorFormatter(fmt="%(message)s"))
    
    # 2. 分级文件持久化 (按等级分类存储)
    os.makedirs("logs", exist_ok=True)
    
    file_formatter = PlainFileFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    def _create_file_handler(filename: str, levels: list) -> TimedRotatingFileHandler:
        # 💡 使用 TimedRotatingFileHandler 实现按天切割，并自动清理 30 天前的旧日志
        handler = TimedRotatingFileHandler(
            filename,
            when="midnight",  # 每天午夜 00:00 执行切割
            interval=1,       # 间隔为 1 (天)
            backupCount=30,   # 仅保留最近 30 份(天)的历史日志，超期的自动从磁盘永久删除
            encoding="utf-8"
        )
        handler.suffix = "%Y-%m-%d"  # 切割后的历史文件名将带有日期后缀 (如 info.log.2026-06-11)
        handler.setFormatter(file_formatter)
        handler.addFilter(LevelFilter(levels))
        return handler

    debug_handler = _create_file_handler("logs/debug.log", [logging.DEBUG])
    info_handler = _create_file_handler("logs/info.log", [logging.INFO])
    warning_handler = _create_file_handler("logs/warning.log", [logging.WARNING])
    error_handler = _create_file_handler("logs/error.log", [logging.ERROR, logging.CRITICAL])
    
    # 准备好分发列表：终端显示、各级文件落盘
    handlers_for_listener = [
        console_handler, 
        debug_handler, 
        info_handler, 
        warning_handler, 
        error_handler
    ]

    # 3. 🚨 全局严重错误报警拦截器
    # 只要在 .env 中配置了 ALERT_WEBHOOK_URL，就会自动激活
    webhook_url = os.getenv("ALERT_WEBHOOK_URL")
    if webhook_url:
        webhook_handler = WebhookAlertHandler(webhook_url)
        webhook_handler.setLevel(logging.ERROR)  # 核心：仅拦截 ERROR 及以上的严重熔断异常
        webhook_handler.setFormatter(PlainFileFormatter(fmt="%(message)s"))
        handlers_for_listener.append(webhook_handler)

    # 4. 性能优化：无阻塞异步队列分发机制
    log_queue = Queue(-1)
    queue_handler = QueueHandler(log_queue)
    
    # 开启后台守护线程，一次性将队列内容分发给所有 handler
    listener = QueueListener(log_queue, *handlers_for_listener, respect_handler_level=True)
    listener.start()
    atexit.register(listener.stop)  # 保证进程退出前，内存队列中的日志能被刷入磁盘

    # 5. 基础配置：让整个 Python 进程默认的 Root Logger 仅写入内存队列
    logging.basicConfig(
        level=level,
        handlers=[queue_handler]
    )

    # 5. 获取量化项目主 Logger
    logger = logging.getLogger("quant_agent")

    # 6. 接管 FastAPI 和 Uvicorn 的默认日志，消除格式不一的问题
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers = []     # 清空其自带的 Handler
        uvicorn_logger.propagate = True  # 让日志向上冒泡，被我们的 RichHandler 捕获并渲染

    # 特殊处理：降低 SQLAlchemy 引擎在 INFO 级别下的刷屏噪音
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return logger

# 导出一个单例 logger 供全局直接导入使用
logger = configure_logging()