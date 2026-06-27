from typing import Any
import os
import zlib

def safe_float(val: Any, default: float = 0.0) -> float:
    """
    安全地将任意类型的值转换为浮点数，若遇到 None 或转换失败则优雅地返回默认值。
    """
    try:
        return float(val)
    except (ValueError, TypeError, Exception):
        return default

def safe_divide(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    """
    安全地执行除法运算，防范 ZeroDivisionError 及类型异常。
    当除数为 0 或发生转换错误时，优雅地返回默认值。
    """
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0.0:
            return default
        return num / den
    except (ValueError, TypeError, ZeroDivisionError, Exception):
        return default

def safe_truncate(text: str, max_length: int, suffix: str = "\n\n...[内容过长，已自适应安全截断，省略 {omitted} 字符]...") -> str:
    """
    自适应安全截断：寻找最近的标点符号或换行符，防止将单词、URL 或 JSON/Markdown 标签从中间硬劈开
    """
    if not isinstance(text, str) or len(text) <= max_length:
        return str(text)
        
    truncate_idx = max_length
    for sep in ['\n\n', '\n', '。', '.', '！', '!', '？', '?', '}', ']', ' ']:
        idx = text.rfind(sep, max(0, max_length - 500), max_length)
        if idx != -1:
            truncate_idx = idx + len(sep)
            break
            
    omitted = len(text) - truncate_idx
    return text[:truncate_idx] + suffix.format(omitted=omitted)

def is_my_shard(identifier: str) -> bool:
    """
    分布式任务分片 (Sharding) 判断。
    利用 zlib.crc32 将任务 identifier (如股票代码) 稳定映射到 [0, WORKER_TOTAL-1]。
    """
    worker_total = int(os.getenv("WORKER_TOTAL", "1"))
    if worker_total <= 1:
        return True
    worker_id = int(os.getenv("WORKER_ID", "0"))
    return zlib.crc32(identifier.encode('utf-8')) % worker_total == worker_id