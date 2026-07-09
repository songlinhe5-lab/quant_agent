"""
Futu 数据源管理 API

提供运行时数据源诊断与连接切换能力:
- GET  /api/v1/futu/source  — 查询当前数据源状态
- PUT  /api/v1/futu/host    — 切换 OpenD 连接目标 (switch_host)
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.futu_service import futu_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/futu", tags=["futu-admin"])


# ── 请求模型 ──────────────────────────────────────────────────────


class SwitchHostRequest(BaseModel):
    """切换 OpenD 连接目标"""

    host: str = Field(..., description="OpenD 主机地址 (IP 或域名)")
    port: int = Field(default=11111, description="OpenD 端口")


# ── API 端点 ──────────────────────────────────────────────────────


@router.get("/source")
async def get_source_status():
    """
    查询当前 Futu 数据源状态。

    返回:
    - mode: 当前模式 (始终为 local)
    - local: 本地直连 OpenD 状态
    """
    return {"code": 0, "data": futu_service.source_router.status()}


@router.get("/diagnose")
async def diagnose_futu_chain(ticker: str = "HK.00700"):
    """诊断 Futu 数据源全链路 — 定位 OpenD 连接状态"""
    import traceback

    diag = {"steps": [], "router_state": {}}

    # Step 0: SourceRouter 内部状态
    router_obj = futu_service.source_router
    diag["router_state"] = {
        "mode": router_obj.current_mode,
        "local_is_available": router_obj._local.is_available,
        "futu_service_status": futu_service.status,
        "conn_mgr_status": futu_service.conn_mgr.status,
    }

    # Step 1: FutuService.get_quote 端到端
    try:
        quote_result = await futu_service.get_quote(ticker)
        diag["steps"].append(
            {
                "step": "futu_service_get_quote",
                "ok": quote_result.get("status") == "success",
                "result_status": quote_result.get("status"),
                "message": quote_result.get("message", ""),
                "result_keys": list(quote_result.keys()) if isinstance(quote_result, dict) else "N/A",
            }
        )
    except Exception as e:
        diag["steps"].append(
            {
                "step": "futu_service_get_quote",
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-500:],
            }
        )

    return {"code": 0, "data": diag}


@router.put("/host")
async def switch_opend_host(req: SwitchHostRequest):
    """
    运行时切换 OpenD 连接目标地址。

    典型场景:
    - 切回本地: {"host": "127.0.0.1", "port": 11111}

    注意: 切换会断开现有连接并尝试重新连接到新目标。
    """
    result = futu_service.conn_mgr.switch_host(req.host, req.port)
    # 同步 FutuService 的状态
    futu_service.status = futu_service.conn_mgr.status
    futu_service.error_msg = futu_service.conn_mgr.error_msg
    futu_service.quote_ctx = futu_service.conn_mgr.quote_ctx

    logger.info(f"[FutuAdmin] OpenD 连接目标切换: {result}")
    return {"code": 0, "data": result}
