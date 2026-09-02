"""mootdx 行情客户端管理（同步 socket，worker 侧 to_thread 调用）。

TDX 免费服务器无 SLA 且 IP 列表会漂移：
- 生产用 TDX_SERVER_IP 显式指定（跳过 bestip 测速）；
- 未指定时 bestip=True 自动测速选优（首次慢，结果落盘复用）；
- 连接断开由 _get_client 捕获后重建（tdxpy 不自动重连）。
"""

from __future__ import annotations

import os
import threading
from typing import Any

from data_subservice._internal.logger import logger

_client_lock = threading.Lock()
_client: Any = None

# TDX K 线类别（tdxpy 协议原生枚举）；对外用别名，内部映射回 int
FREQ_MAP = {
    "5m": 0,
    "15m": 1,
    "30m": 2,
    "60m": 3,
    "day": 9,
    "week": 10,
    "month": 11,
}


def normalize_tdx_symbol(symbol: str) -> str:
    """sh.600000 / 600000 → 600036（mootdx 裸 6 位码，市场由协议侧判）。"""
    s = (symbol or "").strip().lower()
    code = s.split(".", 1)[1] if "." in s else s
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法 A 股代码: {symbol}")
    return code


def _get_client() -> Any:
    """进程级单例 client；断线/异常由调用方 reset_client 后重建。"""
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        from mootdx.quotes import Quotes  # 延迟导入：未装 SDK 的环境不炸

        ip = os.getenv("TDX_SERVER_IP", "").strip()
        if ip:
            _client = Quotes.factory(market="std", ip=ip, timeout=10)
            logger.info(f"[TDX] 行情客户端连接指定服务器 {ip}")
        else:
            _client = Quotes.factory(market="std", bestip=True, timeout=10)
            logger.info("[TDX] 行情客户端 bestip 自动选优")
        return _client


def reset_client() -> None:
    global _client
    with _client_lock:
        _client = None


def call_client(fn_name: str, *args: Any, **kwargs: Any) -> Any:
    """带断线重建的一次调用：失败 → reset → 重试一次，仍败抛错。"""
    try:
        return getattr(_get_client(), fn_name)(*args, **kwargs)
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.warning(f"⚠️ [TDX] {fn_name} 首调失败将重建连接重试: {e}")
        reset_client()
        return getattr(_get_client(), fn_name)(*args, **kwargs)
