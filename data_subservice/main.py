"""
==========================================
Quant Agent — 数据源子服务 (Data Subservice)
==========================================

作为「数据源节点」在远程 VPS 上独立运行，仅暴露数据代理能力。
根据 DS_CAPABILITIES 决定本节点提供哪些数据源能力:
  - yfinance : 美股/加密货币/外汇 (US-West 节点, US-YF-A / US-YF-B)
  - tushare  : A股日线/实时/基本面/沪深港通 (北京从节点)
  - akshare  : 沪深港通资金流向等 (北京从节点)

主节点经 DataSourceRouter 通过 Tailscale 内网调用本服务。

启动:
  DS_CAPABILITIES=yfinance   python -m data_subservice.main
  DS_CAPABILITIES=tushare,akshare  python -m data_subservice.main
"""

import logging
import os

import uvicorn
from fastapi import FastAPI

from data_subservice.nodeinfo import get_node_info
from data_subservice.routes import router, set_capabilities

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data_subservice")

app = FastAPI(title="Quant Agent Data Subservice")
app.include_router(router)

NODE_INFO = get_node_info()
CAPS = NODE_INFO.capabilities
set_capabilities(CAPS)

# 仅 yfinance 能力需要常驻 worker；tushare/akshare 为按需代理，无需轮询。
if "yfinance" in CAPS:
    from data_subservice import yfinance_worker  # noqa: F401


@app.on_event("startup")
async def startup():
    logger.info("[DataSubservice] 节点启动: %s | region=%s | caps=%s", NODE_INFO.node_id, NODE_INFO.region, CAPS)

    if "yfinance" in CAPS:
        await yfinance_worker.start()

    logger.info("[DataSubservice] 心跳上报至主节点 Redis (REDIS_HOST=%s)", os.getenv("REDIS_HOST", "未配置"))


@app.on_event("shutdown")
async def shutdown():
    if "yfinance" in CAPS:
        await yfinance_worker.stop()
    logger.info("[DataSubservice] 节点 %s 停止", NODE_INFO.node_id)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node_id": NODE_INFO.node_id,
        "capabilities": CAPS,
        "version": "1.0.0",
    }


if __name__ == "__main__":
    uvicorn.run(
        "data_subservice.main:app",
        host="0.0.0.0",
        port=int(os.getenv("DS_NODE_PORT", "8000")),
        workers=1,
        loop="uvloop",
        http="httptools",
        timeout_keep_alive=65,
    )
