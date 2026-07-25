"""交易路由层 (Trade Router)。

仅承担「请求校验 + HTTP 映射 + 鉴权注入」，所有用例编排逻辑已收口至
`backend.app.trade_app`。下游依赖的 patch 目标应指向 `backend.app.trade_app.*`。

注：`_trade_locks` 在此重新导出，以满足既有测试夹具 `trade_module._trade_locks.clear()`
对 router 命名空间的依赖（它与 `backend.app.trade_app._trade_locks` 是同一对象）。
"""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from backend.app.trade_app import (
    get_account_info,
    get_portfolio,
    get_trades,
    place_order,
)
from backend.core.database import get_db

router = APIRouter(prefix="/trade", tags=["OMS"])


@router.post("/order")
async def place_order_endpoint(
    ticker: str = Body(""),
    action: str = Body(..., description="BUY or SELL"),
    qty: int = Body(0),
    price: float = Body(0.0),
    order_id: str = Body(""),
):
    """接收前端或 Agent 的发单指令，经过杠杆风控校验后，路由给底层券商"""
    return await place_order(ticker, action, qty, price, order_id)


@router.get("/account")
async def get_account_info_endpoint(market: str = "HK"):
    return await get_account_info(market)


@router.get("/portfolio")
async def get_portfolio_endpoint():
    """获取账户核心资产与风控指标"""
    return await get_portfolio()


@router.get("/trades")
def get_trades_endpoint(limit: int = 100, db: Session = Depends(get_db)):
    """从 PostgreSQL 获取最新的交易日志"""
    return get_trades(limit, db)
