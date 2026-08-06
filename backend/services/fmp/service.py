"""
FMP REST 服务（底层数据源，BE-ARCH-04 · 物理解耦裁剪版）

vibe coding 红线（数据源物理隔离）：
  - FMP 数据源连接层（REST 直连 + credit 计数/持久化/指标）已下沉 data_subservice
    （_internal/fmp + fmp_worker.py），经 DataSourceRouter HTTP 访问 source="fmp"。
  - 本文件改为主服务侧的薄壳：签名 (get_quote/get_profile/get_income_statement) 保持不变，
    adapter 零改动；实际 REST 与 credit 预算由子服务完成。
  - 本地降级直连仅作 router 未启用 / 子服务不可达时的兜底，保持签名兼容。

限流：主服务侧不再持有 fmp throttler（限流/配额在子服务 _internal/fmp 内完成）。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://financialmodelingprep.com/api/v3"


def _key() -> str:
    return os.getenv("FMP_API_KEY", "")


def _local_get(action: str, symbol: str, limit: int = 4) -> dict[str, Any]:
    """router 未启用 / 子服务不可达时的本地兜底直连（保持签名兼容）。

    注意：此分支仅兜底，不引入 credit/限流状态机（子服务侧已统一处理）。
    """
    path = {
        "QUOTE": f"/quote/{symbol}",
        "PROFILE": f"/profile/{symbol}",
        "INCOME_STATEMENT": f"/income-statement/{symbol}?limit={limit}",
    }.get(action, "")
    if not path:
        return {"status": "error", "message": f"unknown action {action}"}
    try:
        r = httpx.get(f"{_BASE}{path}", params={"apikey": _key()}, timeout=10.0)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "message": f"FMP local fallback failed: {e}"}
    if r.status_code == 200:
        return {"status": "success", "data": r.json()}
    if r.status_code == 429:
        return {"status": "error", "message": "FMP 429 rate limited", "error_category": "rate_limit"}
    return {"status": "error", "message": f"FMP HTTP {r.status_code}"}


async def _remote_or_local(action: str, symbol: str, limit: int = 4) -> dict[str, Any]:
    """优先经 DataSourceRouter 调子服务；失败/未启用则本地兜底。"""
    try:
        from backend.services.datasource.router import data_source_router

        if data_source_router._enabled:
            node = data_source_router._nodes.get("fmp_master")
            if node and node.status == "healthy":
                params = {"symbol": symbol}
                if action == "INCOME_STATEMENT":
                    params["limit"] = limit
                result = await data_source_router._send_request(
                    node, "fmp", {"source": "fmp", "action": action, "params": params}
                )
                if result.get("status") == "success":
                    return result
                # 子服务明确返回配额耗尽，直接透传，避免本地兜底无脑再打
                if result.get("error_category") == "quota":
                    return result
    except Exception as e:  # noqa: BLE001
        # 任意异常（含 import 失败）降级本地
        from backend.core.logger import logger

        logger.warning(f"[FMP] 远程调用失败，降级本地: {e}")

    return _local_get(action, symbol, limit)


class FMPService:
    """FMP 底层 REST 客户端（路由薄壳 + 本地兜底）。"""

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        return await _remote_or_local("QUOTE", symbol)

    async def get_profile(self, symbol: str) -> dict[str, Any]:
        return await _remote_or_local("PROFILE", symbol)

    async def get_income_statement(self, symbol: str, limit: int = 4) -> dict[str, Any]:
        return await _remote_or_local("INCOME_STATEMENT", symbol, limit)


fmp_service = FMPService()
