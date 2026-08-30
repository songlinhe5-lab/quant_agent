"""进程内日志环形缓冲 (FE-DEBUG-01) — 子服务侧副本（零 backend 依赖）。

与 backend/core/log_buffer.py 同构，供前端 DEBUG 面板经主服务聚合拉取：
主服务 GET {node_url}/logs/recent?after=<id>（HMAC）读取本缓冲增量。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, List

# 缓冲上限（条数）
MAX_ENTRIES = 2000
# 单次增量拉取上限
MAX_FETCH = 500


class RingBuffer:
    """有界日志环形缓冲：append / recent(after_id) / last_id。"""

    def __init__(self, capacity: int = MAX_ENTRIES) -> None:
        self._capacity = capacity
        self._entries: Deque[Dict[str, object]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._next_id = 1

    def append(self, level: str, name: str, message: str) -> None:
        with self._lock:
            entry = {
                "id": self._next_id,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "level": level,
                "name": name,
                "message": message[:2048],
            }
            self._next_id += 1
            self._entries.append(entry)

    def recent(self, after_id: int = 0, limit: int = MAX_FETCH) -> List[Dict[str, object]]:
        """返回 id > after_id 的增量条目；after_id<=0 返回最近 limit 条。"""
        with self._lock:
            if after_id <= 0:
                out = list(self._entries)
            else:
                out = [e for e in self._entries if e["id"] > after_id]
            return out[-limit:]

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._entries[-1]["id"] if self._entries else 0


class RingBufferHandler(logging.Handler):
    """将日志记录写入 RingBuffer（挂在 QueueListener 的 handler 列表内）。"""

    def __init__(self, buffer: RingBuffer, level: int = logging.NOTSET) -> None:
        super().__init__(level)
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 — 兜底，绝不因日志失败影响业务
            message = str(record.msg)
        # 剥离 rich markup 颜色标签（与 PlainFileFormatter 同策略）
        try:
            from rich.text import Text

            message = Text.from_markup(message).plain
        except Exception:  # noqa: BLE001
            pass
        self.buffer.append(record.levelname, record.name, message)


# 模块级单例：logger.py 挂载 + main.py 读取共用同一实例
ring_buffer = RingBuffer()
ring_buffer_handler = RingBufferHandler(ring_buffer)


def get_ring_buffer() -> RingBuffer:
    return ring_buffer
