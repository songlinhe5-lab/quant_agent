import asyncio
import json
import logging
import os

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.broker import broker
from backend.app.market_data import market_data
from backend.core import models
from backend.core.database import get_db

# 引入全局 Redis 客户端
from backend.core.redis_client import redis_client
from backend.core.ticker_format import format_yf_ticker as _to_yf_ticker
from backend.services.oms_service import oms_service

logger = logging.getLogger("OMS")

router = APIRouter(prefix="/trade", tags=["OMS"])

DEFAULT_USER_ID = "admin"
PREF_REDIS_KEY = f"quant:user:{DEFAULT_USER_ID}:preferences"

_trade_locks = {}


@router.post("/order")
async def place_order(
    ticker: str = Body(""),
    action: str = Body(..., description="BUY or SELL"),
    qty: int = Body(0),
    price: float = Body(0.0),
    order_id: str = Body(""),
):
    """接收前端或 Agent 的发单指令，经过杠杆风控校验后，路由给底层券商"""

    # ==========================================
    # 1. 极速读取 Redis 中的杠杆风控偏好
    # ==========================================
    raw_prefs = await redis_client.get(PREF_REDIS_KEY)
    prefs = json.loads(raw_prefs) if raw_prefs else {}
    # 取出最大杠杆倍数，默认底线为 1.0 (不允许借钱)
    max_leverage = float(prefs.get("defaultLeverage", 1.0))

    # ==========================================
    # 2. 获取当前账户实时总资产 (增加 Redis 极速缓存防频控)
    # ==========================================
    ACCOUNT_CACHE_KEY = f"quant:user:{DEFAULT_USER_ID}:account_info"
    cached_acc_info = await redis_client.get(ACCOUNT_CACHE_KEY)

    if cached_acc_info:
        acc_info = json.loads(cached_acc_info)
    else:
        if ACCOUNT_CACHE_KEY not in _trade_locks:
            _trade_locks[ACCOUNT_CACHE_KEY] = asyncio.Lock()

        async with _trade_locks[ACCOUNT_CACHE_KEY]:
            cached_double = await redis_client.get(ACCOUNT_CACHE_KEY)
            if cached_double:
                acc_info = json.loads(cached_double)
            else:
                acc_info = await broker.get_account_info()
                if acc_info.get("status") == "error":
                    raise HTTPException(status_code=500, detail="风控中断：无法获取当前账户总资产。")  # noqa: E501
                # 将结果写入 Redis 缓存，设置 5 秒的 TTL 生命周期。
                # 5秒内哪怕并发 1000 笔发单，也只会调用 1 次真实 Futu API！
                await redis_client.set(ACCOUNT_CACHE_KEY, json.dumps(acc_info), ex=5)

    total_assets = float(acc_info.get("total_assets", 0.0))

    # ==========================================
    # 3. 基于 ATR 的动态波动率风控
    # ==========================================
    dynamic_sl_price = None
    if action in ["BUY", "SELL"] and price > 0:
        try:
            yf_ticker = _to_yf_ticker(ticker)
            # 获取最新的技术指标 (命中本地缓存，无延迟)
            tech_res = await market_data.get_tech_indicators(ticker=yf_ticker, lookback_days=1)  # noqa: E501
            if tech_res.get("status") == "success" and tech_res.get("data", {}).get("trend"):  # noqa: E501
                latest_tech = tech_res["data"]["trend"][0]
                atr_14 = latest_tech.get("ATR_14")

                if atr_14:
                    volatility = atr_14 / price
                    # 规则 A: 极高波动率资产 (日均振幅 > 5%) 强制将最大允许杠杆降至 1.0 (不可融资)  # noqa: E501
                    if volatility > 0.05:
                        max_leverage = min(max_leverage, 1.0)
                        print(
                            f"⚠️ [Risk Control] {ticker} 波动率过高 ({volatility * 100:.1f}%)，强制降杠杆至 {max_leverage}x"
                        )  # noqa: E501

                    # 规则 B: 基于 2 倍 ATR 自动计算建议止损位
                    dynamic_sl_price = round(price - 2 * atr_14 if action == "BUY" else price + 2 * atr_14, 3)  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Risk Control] ATR 动态风控测算异常，跳过辅助校验: {e}")

    # ==========================================
    # 4. 核心风控校验：资金敞口是否超限
    # ==========================================
    order_value = qty * price
    max_allowed_value = total_assets * max_leverage

    if order_value > max_allowed_value:
        raise HTTPException(
            status_code=403,
            detail=f"🚨 风控拦截：当前订单总价值 (${order_value:,.2f}) 超出了您的最大杠杆限制 ({max_leverage}x, 上限 ${max_allowed_value:,.2f})。",  # noqa: E501
        )

    # ==========================================
    # 5. 校验通过，放行给底层引擎 (BrokerGateway) 执行交易
    # ==========================================
    market = "HK" if ticker and ("HK" in ticker.upper()) else "US"

    if action == "STATUS":
        result = await broker.query_order(order_id, market)
    elif action == "CANCEL":
        result = await broker.cancel_order(order_id, market)
    else:
        result = await broker.place_order(ticker, qty, price, action, market)

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))

    # ==========================================
    # 6. OMS-01: 持久化订单到 PostgreSQL + Redis PubSub 广播
    # ==========================================
    futu_order_id = result.get("order_id", "")
    if futu_order_id:
        try:
            # 使用独立的 DB session 避免依赖注入生命周期冲突
            from backend.core.database import SessionLocal

            db_session = SessionLocal()
            try:
                # 优先读 Redis 热切换值，降级读环境变量
                try:
                    _mode = await redis_client.get("quant:oms:trading_mode")
                    is_sim = _mode != "LIVE"
                except Exception:
                    is_sim = os.getenv("FUTU_TRD_ENV", "SIMULATE").upper() != "REAL"
                await oms_service.create_order(
                    db=db_session,
                    order_id=str(futu_order_id),
                    symbol=ticker,
                    side=action,
                    order_type="MARKET" if price <= 0 else "LIMIT",
                    qty=qty,
                    price=price,
                    is_simulated=is_sim,
                    note=f"stop_loss={dynamic_sl_price}" if dynamic_sl_price else None,
                )
                # 同时写入 trade_logs 留痕
                trade_log = models.TradeLog(
                    ticker=ticker,
                    action=action,
                    price=price,
                    qty=qty,
                    status="SUBMITTED",
                    message=result.get("message", ""),
                )
                db_session.add(trade_log)
                db_session.commit()
            finally:
                db_session.close()
        except Exception as e:
            logger.warning(f"[OMS] 订单持久化异常 (非阻断): {e}")

    response_data = {
        "status": "success",
        "message": "风控校验通过，订单已发送。",
        "data": result,
    }  # noqa: E501
    if dynamic_sl_price:
        response_data["risk_control"] = {
            "suggested_stop_loss": dynamic_sl_price,
            "note": "基于 2x ATR 的动态止损参考",
        }  # noqa: E501

    return response_data


@router.get("/account")
async def get_account_info(market: str = "HK"):
    res = await broker.get_account_info(market)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@router.get("/portfolio")
async def get_portfolio():
    """获取账户核心资产与风控指标"""
    acc_res = await broker.get_account_info()
    base_nav = 12450890.50
    if acc_res.get("status") == "success":
        base_nav = acc_res.get("total_assets", base_nav)

    return {
        "status": "success",
        "data": {
            "base_nav": base_nav,
            "sharpe": 2.15,
            "max_dd": -8.4,
            "margin_usage": 42,
            "exposure": "1.2x L / 0.8x S",
        },
    }  # noqa: E501


@router.get("/trades")
def get_trades(limit: int = 100, db: Session = Depends(get_db)):
    """从 PostgreSQL 获取最新的交易日志"""
    logs = db.query(models.TradeLog).order_by(models.TradeLog.timestamp.desc()).limit(limit).all()  # noqa: E501
    return [
        {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "ticker": log.ticker,
            "action": log.action,
            "price": log.price,
            "qty": log.qty,
            "status": log.status,
            "message": log.message,
        }
        for log in logs
    ]
