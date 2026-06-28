"""
Futu OpenD 连接管理模块
负责行情和交易上下文的初始化、连接管理和解锁逻辑
"""
import os
from typing import Dict, Tuple

from futu import (
    RET_OK,
    OpenQuoteContext,
    OpenSecTradeContext,
    SecurityFirm,
    TrdEnv,
    TrdMarket,
)


class ConnectionManager:
    """Futu OpenD 连接管理器"""

    def __init__(self):
        self.quote_ctx = None
        self.trade_ctxs: Dict[Tuple[TrdEnv, TrdMarket], OpenSecTradeContext] = {}
        self.status = "DISCONNECTED"
        self.error_msg = ""

    def connect(self):
        """连接到 Futu OpenD 行情网关"""
        host = os.getenv("FUTU_HOST", "127.0.0.1")
        port = int(os.getenv("FUTU_PORT", 11111))
        try:
            self.quote_ctx = OpenQuoteContext(host=host, port=port)
            self.status = "CONNECTED"
            self.error_msg = ""
            print(f"✅ [ConnectionManager] 成功连接至全局 OpenD 行情网关 ({host}:{port})")  # noqa: E501
        except Exception as e:
            self.status = "ERROR"
            self.error_msg = str(e)
            print(f"❌ [ConnectionManager] 连接 OpenD 失败: {e}")

    def close(self):
        """关闭所有连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
            self.quote_ctx = None
        for ctx in self.trade_ctxs.values():
            ctx.close()
        self.trade_ctxs.clear()
        self.status = "DISCONNECTED"

    def get_trade_context(self, market: TrdMarket, trd_env: TrdEnv) -> OpenSecTradeContext:  # noqa: E501
        """获取或创建交易上下文（单例模式）"""
        key = (trd_env, market)
        if key not in self.trade_ctxs:
            host = os.getenv("FUTU_HOST", "127.0.0.1")
            port = int(os.getenv("FUTU_PORT", 11111))
            self.trade_ctxs[key] = OpenSecTradeContext(
                filter_trdmarket=str(market),
                host=host,
                port=port,
                security_firm=SecurityFirm.FUTUSECURITIES
            )
        return self.trade_ctxs[key]

    async def unlock_trade_if_needed(self, trd_ctx: OpenSecTradeContext):
        """统一提取交易密码解锁逻辑"""
        pwd_unlock = os.getenv("FUTU_TRD_UNLOCK_PWD", "") or os.getenv("FUTU_TRADE_PWD", "")  # noqa: E501
        if pwd_unlock:
            ret, data = await __import__('asyncio').to_thread(
                trd_ctx.unlock_trade, pwd_unlock, is_unlock=True
            )
            if ret != RET_OK:
                print(f"⚠️ [ConnectionManager] 自动解锁接口被拦截或失败: {data}。请确保已在 OpenD 界面手动解锁。")  # noqa: E501
