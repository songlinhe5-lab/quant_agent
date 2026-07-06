"""
Futu 数据源管理 API

提供运行时数据源切换与诊断能力:
- GET  /api/v1/futu/source  — 查询当前数据源模式与状态
- PUT  /api/v1/futu/source  — 切换数据源模式 (local/remote/auto)
- PUT  /api/v1/futu/host    — 切换 OpenD 连接目标 (switch_host)
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.futu_service import futu_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/futu", tags=["futu-admin"])


# ── 请求模型 ──────────────────────────────────────────────────────


class SwitchSourceRequest(BaseModel):
    """切换数据源模式"""

    mode: str = Field(..., description="数据源模式: local | remote | auto")


class SwitchHostRequest(BaseModel):
    """切换 OpenD 连接目标"""

    host: str = Field(..., description="OpenD 主机地址 (IP 或域名)")
    port: int = Field(default=11111, description="OpenD 端口")


# ── API 端点 ──────────────────────────────────────────────────────


@router.get("/source")
async def get_source_status():
    """
    查询当前 Futu 数据源模式与各数据源状态。

    返回:
    - mode: 当前模式 (local/remote/auto)
    - local: 本地直连 OpenD 状态
    - remote: 远程 slave 代理状态
    """
    return {"code": 0, "data": futu_service.source_router.status()}


@router.put("/source")
async def switch_source_mode(req: SwitchSourceRequest):
    """
    运行时切换 Futu 数据源模式。

    模式说明:
    - local:  强制走本地直连 OpenD (ConnectionManager → FUTU_HOST:FUTU_PORT)
    - remote: 强制走远程 slave 代理 (ClusterManager → slave HTTP)
    - auto:   本地优先，本地不可用时自动降级到 remote
    """
    try:
        new_mode = futu_service.source_router.switch_mode(req.mode)
        logger.info(f"[FutuAdmin] 数据源模式切换完成: {new_mode}")
        return {
            "code": 0,
            "data": {
                "mode": new_mode,
                "message": f"数据源模式已切换为: {new_mode}",
            },
        }
    except ValueError as e:
        return {"code": 400, "message": str(e)}


@router.get("/diagnose")
async def diagnose_futu_chain(ticker: str = "HK.00700"):
    """诊断 Futu 数据源全链路 — 定位 master→slave→OpenD 哪一步断裂"""
    import traceback

    from backend.workers.cluster_manager import cluster_manager

    diag = {"steps": []}

    # Step 1: ClusterManager 状态
    try:
        pool = cluster_manager.get_pool("futu")
        diag["steps"].append(
            {
                "step": "cluster_pool",
                "ok": len(pool) > 0,
                "nodes": [{"id": n.node_id, "status": n.status, "host": n.host} for n in pool],
            }
        )
    except Exception as e:
        diag["steps"].append({"step": "cluster_pool", "ok": False, "error": str(e)})

    # Step 2: call_collector 直接测试
    try:
        result = await cluster_manager.call_collector("futu", "fetch_quote", {"ticker": ticker})
        diag["steps"].append(
            {
                "step": "call_collector_fetch_quote",
                "ok": True,
                "result_type": type(result).__name__,
                "result_keys": list(result.keys()) if isinstance(result, dict) else str(result)[:200],
            }
        )
    except Exception as e:
        diag["steps"].append(
            {
                "step": "call_collector_fetch_quote",
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-500:],
            }
        )

    # Step 3: RemoteDataSource.fetch 测试
    try:
        from backend.services.futu.data_source import RemoteDataSource

        remote = RemoteDataSource()
        fetch_result = await remote.fetch("fetch_quote", {"ticker": ticker})
        diag["steps"].append(
            {
                "step": "remote_datasource_fetch",
                "ok": fetch_result is not None,
                "result": str(fetch_result)[:300] if fetch_result else "None",
            }
        )
    except Exception as e:
        diag["steps"].append(
            {
                "step": "remote_datasource_fetch",
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-500:],
            }
        )

    # Step 4: FutuService.get_quote 端到端
    try:
        quote_result = await futu_service.get_quote(ticker)
        diag["steps"].append(
            {
                "step": "futu_service_get_quote",
                "ok": quote_result.get("status") == "success",
                "result_status": quote_result.get("status"),
                "message": quote_result.get("message", ""),
            }
        )
    except Exception as e:
        diag["steps"].append(
            {
                "step": "futu_service_get_quote",
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }
        )

    return {"code": 0, "data": diag}


@router.put("/host")
async def switch_opend_host(req: SwitchHostRequest):
    """
    运行时切换 OpenD 连接目标地址。

    典型场景:
    - master (北京) 直连香港 VPS 的 OpenD:
      {"host": "1.2.3.4", "port": 11111}
    - 切回本地:
      {"host": "127.0.0.1", "port": 11111}

    注意: 切换会断开现有连接并尝试重新连接到新目标。
    """
    result = futu_service.conn_mgr.switch_host(req.host, req.port)
    # 同步 FutuService 的状态
    futu_service.status = futu_service.conn_mgr.status
    futu_service.error_msg = futu_service.conn_mgr.error_msg
    futu_service.quote_ctx = futu_service.conn_mgr.quote_ctx

    logger.info(f"[FutuAdmin] OpenD 连接目标切换: {result}")
    return {"code": 0, "data": result}
