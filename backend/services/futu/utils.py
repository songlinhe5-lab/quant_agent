"""
Futu 工具函数模块
提供通用的 ticker 格式化和判断工具
"""

from __future__ import annotations

import threading

# 动态不支持的标的集合：运行时探测到富途返回 Unknown/不支持错误时，
# 由 mark_futu_unsupported() 动态加入，后续 is_futu_unsupported() 直接命中跳过，
# 避免对同一标的反复发起注定失败的 futu 请求（请求风暴会打爆子服务线程池）。
# 使用进程内内存（主服务单进程共享）；加锁保证并发安全。
_dyn_unsupported: set[str] = set()
_dyn_unsupported_lock = threading.Lock()


def mark_futu_unsupported(ticker: str) -> bool:
    """标记某标的不受富途支持（首次加入返回 True）。

    用于运行时探测：当 futu FUND_FLOW 等返回 Unknown stock 等不支持错误时调用。
    幂等，重复标记不报错。
    """
    if not ticker:
        return False
    t = ticker.upper()
    with _dyn_unsupported_lock:
        if t in _dyn_unsupported:
            return False
        _dyn_unsupported.add(t)
        return True


def is_futu_unsupported(ticker: str) -> bool:
    """判断是否为富途原生不支持的大类资产（外汇、加密货币、特殊宏观商品等）。

    静态规则（符号/硬编码）+ 动态探测结果（mark_futu_unsupported 写入的集合）。
    """
    t = ticker.upper()
    # 静态规则：带有这些符号的通常是雅虎专用的外汇、加密货币、期指等
    if "=" in t or "-" in t or "^" in t:
        return True
    if t in ["DX-Y.NYB", "DGS10", "GC=F", "CL=F", "HG=F"]:
        return True
    # 动态规则：运行时探测到 futu 不支持（如 US.VIX/US.SPX/US.IXIC 等纯点号格式指数）
    if t in _dyn_unsupported:
        return True
    return False


def format_ticker(ticker: str) -> str:
    """格式化 ticker 为 Futu 标准格式"""
    ticker = ticker.upper()
    index_map = {
        "HSI": "HK.800000",
        "HSTECH": "HK.800700",
        "SPX": "US.SPX",
        "NDX": "US.NDX",
        "TSMC": "US.TSM",
        "US.TSMC": "US.TSM",  # 智能纠正用户的惯用称呼
    }
    if ticker in index_map:
        return index_map[ticker]

    if ticker.endswith(".HK") or ticker.startswith("HK."):
        code = ticker.replace(".HK", "").replace("HK.", "")
        return f"HK.{code.zfill(5) if code.isdigit() else code}"

    if ticker.endswith(".SH") or ticker.endswith(".SS"):
        return f"SH.{ticker.replace('.SH', '').replace('.SS', '')}"
    if ticker.endswith(".SZ"):
        return f"SZ.{ticker.replace('.SZ', '')}"
    if ticker.endswith(".US"):
        return f"US.{ticker.replace('.US', '')}"

    if any(ticker.startswith(prefix) for prefix in ["US.", "SH.", "SZ.", "JP.", "SG.", "UK.", "LSE."]):  # noqa: E501
        return ticker

    return f"US.{ticker}"
