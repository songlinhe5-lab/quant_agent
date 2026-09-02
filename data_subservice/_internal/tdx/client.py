"""TDX 行情客户端管理（tdxpy 直连，同步 socket，worker 侧 to_thread 调用）。

直接依赖 tdxpy（通达信协议逆向实现、mootdx 的底层库）而非 mootdx：
mootdx 已停更且硬钉 httpx<0.26，与项目 httpx>=0.27 永久冲突；tdxpy 纯 socket 零 httpx。

- 生产用 TDX_SERVER_IP 显式指定（支持 ip 或 ip:port，跳过服务器池探测）；
- 未指定时按内置服务器池顺序试连，首个成功者即用（不做 bestip 测速，无 httpx）；
- tdxpy 客户端非线程安全：全部调用经 _api_lock 串行；
- 连接断开由 with_tdx 捕获后重建重试一次，仍败抛错由 worker 语义化。
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

from data_subservice._internal.logger import logger

_api_lock = threading.Lock()
_api: Any = None

# 内置公共行情服务器池（TDX 免费服务器无 SLA 且 IP 会漂移，生产务必 TDX_SERVER_IP 显式指定）
DEFAULT_SERVERS: tuple[tuple[str, int], ...] = (
    ("119.147.212.81", 7709),
    ("112.74.214.43", 7727),
    ("106.14.201.131", 7709),
    ("122.51.120.217", 7709),
    ("110.41.147.114", 7709),
)

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
    """sh.600000 / 600000 → 600000（tdxpy 裸 6 位码，市场由 to_market 判）。"""
    s = (symbol or "").strip().lower()
    code = s.split(".", 1)[1] if "." in s else s
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"非法 A 股代码: {symbol}")
    return code


def to_market(code: str) -> int:
    """6 开头 → 沪市(1)；0/3 开头 → 深市(0)；4/8 开头（北交所/三板）tdxpy 标准行情不支持。"""
    if code[0] == "6":
        return 1
    if code[0] in "03":
        return 0
    raise ValueError(f"TDX 标准行情不支持该 A 股代码: {code}（北交所/三板请走 akshare）")


def _get_api() -> Any:
    """进程级单例 API；TDX_SERVER_IP 优先，否则服务器池顺序试连。"""
    global _api
    with _api_lock:
        if _api is not None:
            return _api
        from tdxpy.hq import TdxHq_API  # 延迟导入：未装 SDK 的环境不炸

        api = TdxHq_API()
        server = os.getenv("TDX_SERVER_IP", "").strip()
        if server:
            host, _, port = server.partition(":")
            api.connect(host, int(port or 7709), time_out=10)
            logger.info(f"[TDX] 行情客户端连接指定服务器 {server}")
        else:
            last_err: Exception | None = None
            for host, port in DEFAULT_SERVERS:
                try:
                    api.connect(host, port, time_out=5)
                    logger.info(f"[TDX] 行情客户端连接服务器池 {host}:{port}")
                    break
                except Exception as e:  # noqa: BLE001 - 试连下一个，仅记录
                    last_err = e
            else:
                raise ConnectionError(f"TDX 服务器池全部连接失败: {last_err}")
        _api = api
        return _api


def reset_client() -> None:
    global _api
    with _api_lock:
        _api = None


def with_tdx(fn: Callable[[Any], Any]) -> Any:
    """串行执行 fn(api)：单连接 + 全局锁；断线 → 重建 → 重试一次，仍败抛错。"""
    try:
        return fn(_get_api())
    except (OSError, ConnectionError, RuntimeError) as e:
        logger.warning(f"⚠️ [TDX] 调用失败将重建连接重试: {e}")
        reset_client()
        return fn(_get_api())
