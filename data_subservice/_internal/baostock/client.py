"""BaoStock SDK 连接管理（同步阻塞，worker 侧 to_thread 调用）。

baostock 是进程级全局单连接（官方声明非线程安全），必须整把串行锁；
login 有秒级网络开销 → 幂等（已登录直接返回），失败重置状态供下次重试。
"""

from __future__ import annotations

import threading
from typing import Any

from data_subservice._internal.logger import logger

_bs_lock = threading.Lock()
_logged_in = False


# 6/9 开头 → 沪市；0/2/3 开头 → 深市；4/8 开头（北交所/三板）baostock 不覆盖
def normalize_bs_code(symbol: str) -> str:
    """600000 → sh.600000；000001 → sz.000001；已带前后缀的原样返回（小写归一）。"""
    s = (symbol or "").strip().lower()
    if "." in s:
        return s
    if not s.isdigit() or len(s) != 6:
        raise ValueError(f"非法 A 股代码: {symbol}（期望 6 位数字，如 600000/000001）")
    if s[0] in "69":
        return f"sh.{s}"
    if s[0] in "03":
        return f"sz.{s}"
    raise ValueError(f"baostock 不覆盖该代码段（北交所/三板走其他源）: {symbol}")


def _ensure_login() -> Any:
    """幂等登录：返回 baostock 模块。失败抛异常并重置登录态。"""
    global _logged_in
    import baostock as bs  # 延迟导入：未装 SDK 的环境不炸

    with _bs_lock:
        if _logged_in:
            return bs
        lg = bs.login()
        if lg is None or getattr(lg, "error_code", "1") != "0":
            _logged_in = False
            msg = getattr(lg, "error_msg", "login returned None")
            raise ConnectionError(f"baostock 登录失败: {msg}")
        _logged_in = True
        return bs


def reset_login() -> None:
    """断线/异常后由 service 层调用，下次查询重新 login。"""
    global _logged_in
    with _bs_lock:
        _logged_in = False


def query_rows(bs: Any, rs: Any) -> list[dict[str, str]]:
    """ResultData → list[dict]；错误码非 0 显式失败（结构锁：宁失败不静默拉空）。"""
    if rs is None:
        raise RuntimeError("baostock 返回 None（连接可能已断开）")
    if getattr(rs, "error_code", "1") != "0":
        reset_login()
        raise RuntimeError(f"baostock 查询失败 [{rs.error_code}]: {rs.error_msg}")
    fields = list(rs.fields)
    rows: list[dict[str, str]] = []
    while (rs.error_code == "0") and rs.next():
        rows.append(dict(zip(fields, rs.get_row_data())))
    return rows


def safe_query(bs: Any, fn_name: str, *args: Any, **kwargs: Any) -> list[dict[str, str]]:
    """带断线重试的一次查询：首查失败（连接断开）→ 重置登录 → 重登再试一次。"""
    try:
        return query_rows(bs, getattr(bs, fn_name)(*args, **kwargs))
    except (ConnectionError, RuntimeError, OSError) as e:
        logger.warning(f"⚠️ [BaoStock] {fn_name} 首查失败将重试: {e}")
        reset_login()
        bs2 = _ensure_login()
        return query_rows(bs2, getattr(bs2, fn_name)(*args, **kwargs))
