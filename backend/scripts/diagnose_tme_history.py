"""
诊断脚本：US.TME 历史 K 线多通道探测 (DIAG-2026-08-14)

目的：确认 get_broker_market_data(HISTORY) 对美股标的 US.TME 是不是"只有 akshare 一条路断"，
还是 futu（首选）远程节点熔断导致整体降级到 akshare 也失败。

运行环境：必须在 S1 主服务容器内执行（依赖容器内 env + 已初始化的单例）。
  python backend/scripts/diagnose_tme_history.py

输出：分别经 facade 强制 prefer futu / yfinance / akshare，以及直连 data_source_router.fetch_futu
各路返回的 klines 条数、source 标记、错误信息，一眼定位断点。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys


def _klines_count(data: dict) -> int:
    """从归一化后的 history data 里取 klines 条数。"""
    if not isinstance(data, dict):
        return 0
    k = data.get("klines")
    if isinstance(k, list):
        return len(k)
    # 部分源把数据放在 data["data"]["klines"]
    inner = data.get("data")
    if isinstance(inner, dict):
        k2 = inner.get("klines")
        if isinstance(k2, list):
            return len(k2)
    return 0


async def _probe_facade(prefer: str) -> dict:
    """经 facade.get_history 强制走某一通道。"""
    from backend.services.datasource.business.facade import data_service

    res = await data_service.get_history("US.TME", ktype="K_DAY", num=30, prefer_sources=[prefer])
    info = {
        "channel": prefer,
        "status": getattr(res, "status", None),
        "source": getattr(res, "source", None),
        "klines": _klines_count(getattr(res, "data", None)),
    }
    err = getattr(res, "error", None)
    if err is not None:
        info["error"] = str(err)
    return info


async def _probe_futu_remote() -> dict:
    """直连 data_source_router.fetch_futu 验证 futu 远程子服务本身通不通。"""
    from backend.services.datasource.router import data_source_router

    raw = await data_source_router.fetch_futu("HISTORY", ticker="US.TME", ktype="K_DAY", num=30)
    info = {
        "channel": "futu_remote_direct",
        "raw_keys": list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
    }
    if isinstance(raw, dict):
        info["success"] = raw.get("success")
        info["message"] = raw.get("message")
        data = raw.get("data")
        if isinstance(data, dict):
            info["klines"] = _klines_count(data)
        elif isinstance(data, list):
            info["klines"] = len(data)
    return info


async def main() -> int:
    print("=" * 70)
    print("[DIAG] US.TME 历史K线多通道探测")
    print(f"[DIAG] DATA_SOURCE_ROUTER_ENABLED={os.getenv('DATA_SOURCE_ROUTER_ENABLED')}")
    print(f"[DIAG] DATA_SOURCE_HMAC_SECRET set={bool(os.getenv('DATA_SOURCE_HMAC_SECRET'))}")
    print("=" * 70)

    # 1) facade 强制三路
    for ch in ("futu", "yfinance", "akshare"):
        try:
            info = await _probe_facade(ch)
        except Exception as exc:  # noqa: BLE001
            info = {"channel": ch, "exception": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(info, ensure_ascii=False))

    # 2) 直连 futu 远程子服务
    try:
        info = await _probe_futu_remote()
    except Exception as exc:  # noqa: BLE001
        info = {"channel": "futu_remote_direct", "exception": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(info, ensure_ascii=False))

    print("=" * 70)
    print("[DIAG] 判定：")
    print("  - 若 futu/yfinance 有 klines 而默认返回空 → 是路由降级/熔断问题，非单源断")
    print("  - 若三路全空 → 各通道独立能力问题或环境未连通")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
