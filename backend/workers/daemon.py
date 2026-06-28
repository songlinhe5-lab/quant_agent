import asyncio
import os

import httpx
import pandas as pd
from dotenv import load_dotenv
from futu import RET_OK, StockQuoteHandlerBase

from backend.core import models  # noqa: E402
from backend.core.database import SessionLocal  # noqa: E402
from backend.services.notification_service import notification_service  # noqa: E402

# 1. 优先加载本地环境变量，确保能读取到 FUTU_HOST 等配置
load_dotenv()

# ==========================================
# 策略配置区
# ==========================================
TARGET_TICKER = "US.AAPL"
TARGET_BUY_PRICE = 9990.0  # 假设跌破 150 美元触发买入信号
# 路径向上跳两层 (从 workers 目录跳出到 backend) 以读取数据库
TRADE_LOG_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "trade_logs.db",
)


def init_trade_db():
    """初始化交易日志数据库 (现在由 Alembic/SQLAlchemy 管理，此函数可留空或移除)"""
    pass


def log_trade(ticker, action, price, qty, status, message):
    """将交易记录写入 PostgreSQL"""
    try:
        with SessionLocal() as db:
            log_entry = models.TradeLog(
                ticker=ticker,
                action=action,
                price=float(price),
                qty=int(qty),
                status=str(status),
                message=str(message),
            )
            db.add(log_entry)
            db.commit()
    except Exception as e:
        print(f"⚠️ [数据库] 记录交易日志失败: {e}")


class QuoteMonitorHandler(StockQuoteHandlerBase):
    """
    行情异步回调处理器：当底层网关有最新报价时，会自动触发 on_recv_rsp。
    """

    def __init__(self):
        super().__init__()
        self.has_traded = False

    async def execute_trade(self, ticker: str, action: str, qty: int, price: float):
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        async with httpx.AsyncClient() as client:
            payload = {
                "action": action,
                "ticker": ticker,
                "qty": qty,
                "price": price,
                "order_id": "",
            }
            try:
                resp = await client.post(
                    f"{backend_url}/api/trade/order",
                    json=payload,
                    timeout=10.0,
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                return {"status": "error", "message": f"API 异常: {str(e)}"}

    def on_recv_rsp(self, rsp_pb):
        ret_code, raw_data = super(QuoteMonitorHandler, self).on_recv_rsp(rsp_pb)
        if isinstance(raw_data, pd.DataFrame):
            data: pd.DataFrame = raw_data
        else:
            print(f"⚠️ 非预期的行情数据类型: {type(raw_data)!r}, 内容: {raw_data}")
            return RET_OK, raw_data
        if ret_code != RET_OK:
            print(f"⚠️ 报价接收异常: {data}")
            return RET_OK, data

        ticker = data["code"].iloc[0]
        last_price = data["last_price"].iloc[0]

        if ticker == TARGET_TICKER and last_price <= TARGET_BUY_PRICE and not self.has_traded:
            print(f"\n🚨 [交易信号触发] {ticker} 价格 ({last_price}) 跌破阈值 {TARGET_BUY_PRICE}！")
            self.has_traded = True

            action_type = "BUY"
            trade_qty = 1
            # 走 HTTP 接口调用后端 OMS 系统发单（触发风控检查）
            result = asyncio.run(
                self.execute_trade(
                    ticker=ticker,
                    action=action_type,
                    qty=trade_qty,
                    price=last_price,
                )
            )

            log_trade(
                ticker=ticker,
                action=action_type,
                price=last_price,
                qty=trade_qty,
                status=result.get("status", "unknown"),
                message=result.get("message", ""),
            )

            if result.get("status") == "success":
                print(f"✅ [执行成功] {result.get('message')}\n")
                alert_msg = (
                    "✅ [Quant Agent] 交易成功！\n\n"
                    f"标的: {ticker}\n"
                    f"价格: {last_price}\n"
                    "动作: 买入 1 股\n"
                    f"回执: {result.get('message')}"
                )
                asyncio.run(notification_service.send_alert(alert_msg))
            else:
                print(f"❌ [执行失败] {result.get('message')}\n")
                alert_msg = (
                    "❌ [Quant Agent] 交易受阻！\n\n"
                    f"标的: {ticker}\n"
                    f"当前价格: {last_price}\n"
                    f"失败原因: {result.get('message')}"
                )
                asyncio.run(notification_service.send_alert(alert_msg))

        return RET_OK, data


def start_daemon():
    init_trade_db()
    futu_host = os.getenv("FUTU_HOST", "127.0.0.1")
    futu_port = int(os.getenv("FUTU_PORT", 11111))
    print(f"🚀 启动实时行情监控 Daemon，连接 OpenD ({futu_host}:{futu_port})...")
    # ... 此处略去多余占位，已迁移至新目录


if __name__ == "__main__":
    start_daemon()
