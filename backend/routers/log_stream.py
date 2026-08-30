"""日志流聚合路由 (FE-DEBUG-01) — 前端底部 DEBUG 面板实时日志源。

接口（统一 /api/v1/logs/stream/*）：
  GET /logs/stream/recent   — 主服务自身进程内日志增量（after=上一批最大 id）
  GET /logs/stream/nodes    — 数据子服务节点列表（DataSourceRouter 节点按 URL 去重）
  GET /logs/stream/summary  — 聚合主服务 + 各子节点日志增量（节点经 HMAC GET /logs/recent）

数据流：主服务/子服务各自维护进程内环形缓冲（backend/core/log_buffer.py /
data_subservice/_internal/log_buffer.py），前端每 ~2s 增量轮询 summary。

子服务侧增量端点：GET /logs/recent?after=<id>（HMAC 校验，返回 {code, data:{last_id, entries}}）。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, Query

from backend.core.log_buffer import ring_buffer
from backend.core.logger import logger
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/logs/stream", tags=["Log Stream"])

# 主服务 → 子服务 HMAC 签名（与 data_subservice/main.py verify_hmac 约定一致：
# message = f"{ts}:{body}"，GET 请求 body 为空字符串）
_HMAC_SECRET = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
_NODE_TIMEOUT = 3.0


def _hmac_headers() -> Dict[str, str]:
    ts = str(int(time.time()))
    message = f"{ts}:".encode("utf-8")
    signature = hmac.new(_HMAC_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": signature}


async def _fetch_node_recent(url: str, after: int) -> Dict[str, Any]:
    """经 HMAC 拉取单个子节点日志增量；失败抛异常由调用方降级。"""
    async with httpx.AsyncClient(timeout=_NODE_TIMEOUT) as client:
        resp = await client.get(
            f"{url}/logs/recent",
            params={"after": max(after, 0)},
            headers=_hmac_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def _collect_nodes() -> List[Dict[str, Any]]:
    """从 DataSourceRouter 收集数据子服务节点，按 URL 去重（多能力节点共享同 URL）。"""
    try:
        from backend.services.datasource.router import data_source_router

        status = await data_source_router.get_health_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[LogStream] 节点列表读取失败: {e}")
        return []

    grouped: Dict[str, Dict[str, Any]] = {}
    for name, node in status.get("nodes", {}).items():
        url = (node.get("url") or "").strip()
        if not url:
            continue
        entry = grouped.setdefault(url, {"url": url, "names": [], "online": False})
        entry["names"].append(node.get("name", name))
        if node.get("status") in ("healthy", "online"):
            entry["online"] = True
    return [
        {
            "url": url,
            "name": url.replace("http://", "").replace("https://", "").rstrip("/"),
            "aliases": sorted(entry["names"]),
            "online": entry["online"],
        }
        for url, entry in sorted(grouped.items())
    ]


@router.get("/recent")
async def recent_logs(
    after: int = Query(0, ge=0, description="只返回 id 大于此值的日志（增量游标）"),
    limit: int = Query(200, ge=1, le=500),
    _username: str = Depends(get_current_user),
):
    """主服务自身进程内日志增量。

    返回 {code, data} 信封：backend/middleware/stack.py 的 response_envelope_middleware
    对含 code 键的响应直接透传，避免二次包装为 {code, msg, data:{code,data:...}}。
    与子服务 /logs/recent 格式对齐，前端统一取 res.data.data。
    """
    entries = ring_buffer.recent(after_id=after, limit=limit)
    return {
        "code": 0,
        "data": {"last_id": ring_buffer.last_id, "entries": entries},
    }


@router.get("/nodes")
async def log_nodes(_username: str = Depends(get_current_user)):
    """数据子服务节点列表（DEBUG 面板动态分栏依据）。"""
    nodes = await _collect_nodes()
    return {"code": 0, "data": {"nodes": nodes, "total": len(nodes)}}


@router.get("/summary")
async def log_summary(
    after: int = Query(0, ge=0, description="主服务日志增量游标"),
    nodes: str = Query("{}", description='节点增量游标 JSON，如 {"http://localhost:8001":123}'),
    _username: str = Depends(get_current_user),
):
    """聚合主服务 + 各数据子服务节点日志增量（前端单次轮询一次拉全）。"""
    try:
        node_cursors: Dict[str, int] = json.loads(nodes) if nodes else {}
    except json.JSONDecodeError:
        node_cursors = {}

    main_entries = ring_buffer.recent(after_id=after, limit=500)
    main_payload = {"last_id": ring_buffer.last_id, "entries": main_entries}

    node_list = await _collect_nodes()
    results: List[Dict[str, Any]] = [None] * len(node_list)  # type: ignore[list-item]

    async def _gather_one(idx: int, url: str) -> None:
        try:
            body = await _fetch_node_recent(url, node_cursors.get(url, 0))
            data = body.get("data", {}) if isinstance(body, dict) else {}
            results[idx] = {
                "url": url,
                "status": "ok",
                "last_id": int(data.get("last_id", 0)),
                "entries": data.get("entries", []),
            }
        except Exception as e:  # noqa: BLE001 — 节点不可达降级为 error 标记
            results[idx] = {
                "url": url,
                "status": "error",
                "error": str(e)[:200],
                "last_id": node_cursors.get(url, 0),
                "entries": [],
            }

    await asyncio.gather(*[_gather_one(i, n["url"]) for i, n in enumerate(node_list)])

    # 合并节点元信息（名称/别名/在线）与日志负载
    for idx, node in enumerate(node_list):
        results[idx].update({k: v for k, v in node.items() if k != "url"})

    return {
        "code": 0,
        "data": {"main": main_payload, "nodes": results},
    }
