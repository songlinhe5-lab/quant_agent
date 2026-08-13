"""
Futu OpenD 连接管理模块
负责行情和交易上下文的初始化、连接管理和解锁逻辑

支持运行时切换连接目标 (switch_host):
- 本地开发: FUTU_HOST=127.0.0.1 (默认)
- 远程直连: FUTU_HOST=<香港VPS_IP> (master 直连远程 OpenD)
"""

import logging
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

logger = logging.getLogger(__name__)


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
        # Futu 连接能力由 data_subservice 的 DS_CAPABILITIES=futu 在外层门控；
        # 此处默认开启连接逻辑，无 OpenD 时由 status/error_msg 在监控呈现，不静默禁用。
        self._enabled = True

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
        """连接到 Futu OpenD 行情网关（线程安全）

        ⚠️ 线程泄漏防护 (2026-08-13 根因修复):
        futu.OpenQuoteContext 内部会启动一组独立的 callback_executor 线程
        (idle 在 queue.get())，context 被 GC 前不会 join。若此处直接 new 一个
        新 ctx 覆盖 self.quote_ctx 而不 close 旧 ctx，旧 ctx 的回调线程将永久
        泄漏。watchdog._health_check 在探针失败时把 status 改成 DISCONNECTED
        (但不清空 quote_ctx)，旧逻辑据此双重检查失败 → 反复 new ctx → 线程累积
        至 OOM(实测 35min 爬到 814 个 futu 回调线程)。

        修复:
        1) 只要 self.quote_ctx 仍存活就一律复用，不被 watchdog 的 DISCONNECTED
           状态误杀 (ctx 对象本身还在，没必要重建)。
        2) 真正需要重建时，先 close 掉旧 ctx 释放其回调线程，再 new。
        """
        # 线程安全：防止并发连接
        with self._lock:
            # 双重检查：ctx 对象仍存活即复用，避免覆盖式泄漏
            if self.quote_ctx is not None:
                if self.status != "CONNECTED":
                    # ctx 在但状态被 watchdog 标记断线：复用现有 ctx，
                    # 让 watchdog 负责重连，这里不抢建连。
                    print("♻️ [ConnectionManager] ctx 已存在，复用并保留供 watchdog 重连")
                else:
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
                # 🛡️ 兜底：建新 ctx 前若仍有旧 ctx 残留(异常路径)，先释放其线程
                if self.quote_ctx is not None:
                    try:
                        self.quote_ctx.close()
                    except Exception:
                        pass
                    self.quote_ctx = None

                self.quote_ctx = OpenQuoteContext(host=self._host, port=self._port)
                self.status = "CONNECTED"
                self.error_msg = ""
                print(f"✅ [ConnectionManager] 成功连接至全局 OpenD 行情网关 ({self._host}:{self._port})")  # noqa: E501

                # 注册推送回调处理器（将 Futu 实时推送桥接到 Redis PubSub）
                self._register_push_handlers()
            except Exception as e:
                self.status = "ERROR"
                self.error_msg = str(e)
                print(f"❌ [ConnectionManager] 连接 OpenD 失败: {e}")

    def _register_push_handlers(self):
        """连接成功后注册所有推送回调处理器，并捕获主事件循环引用"""
        if not self.quote_ctx:
            return
        try:
            # 捕获当前事件循环，供推送回调跨线程桥接使用
            import asyncio

            from . import push_handler

            try:
                loop = asyncio.get_running_loop()
                push_handler.set_main_loop(loop)
            except RuntimeError:
                # BE-ARCH-08c①: connect() 经 asyncio.to_thread 在工作线程执行，此处无
                # running loop。回退到主线程已 set 的事件循环引用（startup_event 已
                # set_main_loop 双保险），否则 _main_loop 恒为 None，后续所有推送回调
                # 经 _schedule_coroutine 静默丢弃。
                try:
                    push_handler.set_main_loop(asyncio.get_event_loop())
                except RuntimeError:
                    logger.warning("[ConnectionManager] 无法获取事件循环，推送桥接将不可用")

            # 检查是否启用推送模式（默认开启）
            push_enabled = os.getenv("FUTU_PUSH_ENABLED", "true").lower() == "true"
            if not push_enabled:
                print("ℹ️ [ConnectionManager] 推送模式已禁用 (FUTU_PUSH_ENABLED=false)")
                return

            results = push_handler.register_all_handlers(self.quote_ctx)
            success = sum(1 for v in results.values() if v)
            if success > 0:
                print(f"📡 [ConnectionManager] 推送模式已激活 ({success} 个处理器)")
            else:
                print("⚠️ [ConnectionManager] 无推送处理器注册成功，退化为拉取模式")
        except Exception as e:
            logger.warning(f"[ConnectionManager] 注册推送处理器异常: {e}")

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
                raise ConnectionError(f"OpenD 不可达 ({self._host}:{self._port})，拒绝创建交易上下文")
            # 💡 跨网络连接必须启用加密（Futu 安全要求）
            # 当 host 是 localhost/127.0.0.1 时，视为本地连接，不启用加密
            is_cross_network = self._host not in ["127.0.0.1", "localhost", "::1"]
            self.trade_ctxs[key] = OpenSecTradeContext(
                filter_trdmarket=str(market),
                host=self._host,
                port=self._port,
                is_encrypt=is_cross_network,  # 跨网络启用加密，本地不加密
                security_firm=SecurityFirm.FUTUSECURITIES,
            )
        return self.trade_ctxs[key]

    async def unlock_trade_if_needed(self, trd_ctx: OpenSecTradeContext) -> bool:
        """统一提取交易密码解锁逻辑。

        返回是否解锁成功 (True=已解锁/无需解锁, False=解锁失败)。
        DIST-23(2026-08-11 实战): 此前解锁失败仅打印警告、无返回值, 导致上层
        get_account_info 无法区分"未解锁"与"常规错误", 最终 error 上抛触发主服务
        futu_master 全局熔断误杀行情。现显式返回锁定状态供上层隔离处理。
        """
        pwd_unlock = os.getenv("FUTU_TRD_UNLOCK_PWD", "") or os.getenv("FUTU_TRADE_PWD", "")  # noqa: E501
        if not pwd_unlock:
            # 未配置解锁密码: 视为需要手动在 OpenD 界面解锁 (非故障, 标记锁定)
            print("⚠️ [ConnectionManager] 未配置 FUTU_TRD_UNLOCK_PWD, 交易需手动在 OpenD 界面解锁。")
            return False
        ret, data = await __import__("asyncio").to_thread(trd_ctx.unlock_trade, pwd_unlock, is_unlock=True)
        if ret != RET_OK:
            print(f"⚠️ [ConnectionManager] 自动解锁接口被拦截或失败: {data}。请确保已在 OpenD 界面手动解锁。")  # noqa: E501
            return False
        return True

    # ── 运行时切换连接目标 ──────────────────────────────────────────

    def switch_host(self, host: str, port: int = 11111) -> Dict[str, str]:
        """
        运行时切换 OpenD 连接目标。

        典型场景:
        - master (北京) 直连香港 VPS 的 OpenD:
            switch_host("1.2.3.4", 11111)
        - 切回本地:
            switch_host("127.0.0.1", 11111)

        Args:
            host: OpenD 主机地址 (IP 或域名)
            port: OpenD 端口 (默认 11111)

        Returns:
            切换结果 dict
        """
        old_host, old_port = self._host, self._port

        if host == old_host and port == old_port:
            return {"status": "unchanged", "host": host, "port": port}

        # 1. 关闭现有连接
        was_connected = self.status == "CONNECTED"
        if was_connected:
            self.close()

        # 2. 更新目标地址
        self._host = host
        self._port = port

        logger.info(f"[ConnectionManager] 连接目标切换: {old_host}:{old_port} → {host}:{port}")

        # 3. 尝试重新连接
        self.connect()

        return {
            "status": self.status,
            "old_host": old_host,
            "old_port": old_port,
            "new_host": host,
            "new_port": port,
            "reconnected": self.status == "CONNECTED",
        }

    @property
    def target(self) -> str:
        """当前连接目标地址"""
        return f"{self._host}:{self._port}"
