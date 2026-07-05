"""
Futu OpenD 连接管理模块
负责行情和交易上下文的初始化、连接管理和解锁逻辑
"""

import os
import threading
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
        self._host = os.getenv("FUTU_HOST", "127.0.0.1")
        self._port = int(os.getenv("FUTU_PORT", 11111))
        self._lock = threading.Lock()  # 防止并发连接
        # 联动 COLLECTOR_FUTU (新) 并保留 FUTU_ENABLED (旧) 向后兼容
        _futu_env = os.getenv("FUTU_ENABLED")
        if _futu_env is not None:
            self._enabled = _futu_env.lower() == "true"
        else:
            self._enabled = os.getenv("COLLECTOR_FUTU", "false").lower() == "true"

    def _is_opend_reachable(self, timeout: float = 2.0) -> bool:
        """
        快速探测 OpenD 是否可连接（避免 futu-api 内部疯狂重试）

        Args:
            timeout: 探测超时时间（秒）

        Returns:
            bool: OpenD 可连接返回 True，否则返回 False
        """
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect((self._host, self._port))
            return True
        except Exception:
            return False

    def connect(self):
        """连接到 Futu OpenD 行情网关（线程安全）"""
        # 检查是否启用富途
        if not self._enabled:
            self.status = "DISABLED"
            self.error_msg = "富途服务已禁用 (COLLECTOR_FUTU=false)"
            print("⚠️ [ConnectionManager] 富途服务已禁用，跳过连接")
            return

        # 线程安全：防止并发连接
        with self._lock:
            # 双重检查：如果已连接，直接返回
            if self.status == "CONNECTED" and self.quote_ctx is not None:
                print("✅ [ConnectionManager] 已连接，跳过重复连接")
                return

            # 快速探测：如果 OpenD 不可达，提前返回，避免 futu-api 内部重试
            if not self._is_opend_reachable():
                self.status = "ERROR"
                self.error_msg = f"OpenD 不可达 ({self._host}:{self._port})"
                print(f"❌ [ConnectionManager] OpenD 不可达，跳过连接: {self._host}:{self._port}")
                return

            # OpenD 可连接，再创建上下文
            try:
                self.quote_ctx = OpenQuoteContext(host=self._host, port=self._port)
                self.status = "CONNECTED"
                self.error_msg = ""
                print(f"✅ [ConnectionManager] 成功连接至全局 OpenD 行情网关 ({self._host}:{self._port})")  # noqa: E501
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
            # 快速探测：OpenD 不可达时拒绝创建，防止 Futu SDK 后台线程无限重试
            if not self._is_opend_reachable():
                raise ConnectionError(
                    f"OpenD 不可达 ({self._host}:{self._port})，拒绝创建交易上下文"
                )
            host = os.getenv("FUTU_HOST", "127.0.0.1")
            port = int(os.getenv("FUTU_PORT", 11111))
            self.trade_ctxs[key] = OpenSecTradeContext(
                filter_trdmarket=str(market),
                host=host,
                port=port,
                security_firm=SecurityFirm.FUTUSECURITIES,
            )
        return self.trade_ctxs[key]

    async def unlock_trade_if_needed(self, trd_ctx: OpenSecTradeContext):
        """统一提取交易密码解锁逻辑"""
        pwd_unlock = os.getenv("FUTU_TRD_UNLOCK_PWD", "") or os.getenv("FUTU_TRADE_PWD", "")  # noqa: E501
        if pwd_unlock:
            ret, data = await __import__("asyncio").to_thread(trd_ctx.unlock_trade, pwd_unlock, is_unlock=True)
            if ret != RET_OK:
                print(f"⚠️ [ConnectionManager] 自动解锁接口被拦截或失败: {data}。请确保已在 OpenD 界面手动解锁。")  # noqa: E501
