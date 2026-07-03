"""
BE-03: Futu OpenD 看门狗守护进程

职责：
1. 定期健康检查（尝试获取快照验证连接活性）
2. 断连检测后自动重连，重连间隔采用指数退避策略
3. 重连失败次数达到阈值后触发熔断，避免无限死循环
4. 重连成功后自动恢复订阅（重新订阅之前丢失的主题）
5. 通过 Prometheus 指标暴露重连次数与状态

架构：
- 独立 asyncio Task，与 broadcast_loop 解耦
- 通过 ConnectionManager.status 感知连接状态
- 指数退避：base_delay * 2^attempt，上限 max_delay
"""

import asyncio
import time
from typing import Optional

import structlog

from backend.core.metrics import (
    FUTU_CONNECTION_STATUS,
    FUTU_RECONNECT_FAILURES,
    FUTU_RECONNECT_TOTAL,
)

logger = structlog.get_logger(__name__)


class FutuWatchdog:
    """
    Futu OpenD 连接看门狗

    使用示例：
        watchdog = FutuWatchdog(futu_service_instance)
        asyncio.create_task(watchdog.start())
    """

    # ── 退避策略参数 ──────────────────────────────────────────────
    BASE_DELAY: float = 2.0  # 首次重连等待 2s
    MAX_DELAY: float = 120.0  # 最大退避 120s
    BACKOFF_FACTOR: float = 2.0  # 指数因子
    JITTER: float = 0.3  # 随机抖动比例（防止惊群效应）

    # ── 健康检查参数 ──────────────────────────────────────────────
    HEALTH_CHECK_INTERVAL: float = 15.0  # 每 15s 做一次健康检查
    HEALTH_PROBE_SYMBOL: str = "HK.00700"  # 用腾讯控股做探针
    HEALTH_TIMEOUT: float = 5.0  # 探针超时 5s

    # ── 熔断保护 ──────────────────────────────────────────────
    MAX_CONSECUTIVE_FAILURES: int = 20  # 连续失败 20 次后进入长休眠
    LONG_SLEEP: float = 300.0  # 长休眠 5 分钟后再尝试

    def __init__(self, futu_svc):
        """
        Args:
            futu_svc: FutuService 全局单例（backend.services.futu.futu_service）
        """
        self._futu = futu_svc
        self._conn_mgr = futu_svc.conn_mgr
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 退避状态
        self._consecutive_failures: int = 0
        self._total_reconnects: int = 0
        self._last_reconnect_ts: float = 0
        self._last_success_ts: float = 0

    async def start(self) -> None:
        """启动看门狗守护协程（幂等，重复调用安全）"""
        if self._running:
            logger.warning("[FutuWatchdog] 看门狗已在运行，跳过重复启动")
            return

        self._running = True
        logger.info("[FutuWatchdog] 🐕 看门狗守护进程启动")

        try:
            while self._running:
                try:
                    await self._watchdog_loop()
                except asyncio.CancelledError:
                    logger.info("[FutuWatchdog] 收到取消信号，优雅退出")
                    break
                except Exception as e:
                    logger.error(f"[FutuWatchdog] 看门狗主循环异常: {e}", exc_info=True)
                    await asyncio.sleep(5)
        finally:
            self._running = False
            FUTU_CONNECTION_STATUS.set(0)
            logger.warning("[FutuWatchdog] 看门狗已停止")

    async def _watchdog_loop(self) -> None:
        """核心看门狗循环"""
        while self._running:
            # 1. 健康检查
            is_healthy = await self._health_check()

            if is_healthy:
                # 连接正常，重置退避计数器
                if self._consecutive_failures > 0:
                    logger.info(
                        f"[FutuWatchdog] ✅ 连接恢复正常 (此前连续失败 {self._consecutive_failures} 次)"  # noqa: E501
                    )
                self._consecutive_failures = 0
                self._last_success_ts = time.monotonic()
                FUTU_CONNECTION_STATUS.set(1)

                # 正常状态：等待下次健康检查
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                continue

            # 2. 连接异常 → 触发重连
            FUTU_CONNECTION_STATUS.set(0)
            self._consecutive_failures += 1
            self._total_reconnects += 1
            FUTU_RECONNECT_TOTAL.inc()

            # 3. 计算退避延迟
            if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
                # 超过最大连续失败次数 → 长休眠
                delay = self.LONG_SLEEP
                logger.warning(
                    f"[FutuWatchdog] 🚨 连续失败 {self._consecutive_failures} 次，进入长休眠 {delay}s 后重试"
                )
            else:
                # 指数退避 + 随机抖动
                delay = min(
                    self.BASE_DELAY * (self.BACKOFF_FACTOR ** (self._consecutive_failures - 1)),  # noqa: E501
                    self.MAX_DELAY,
                )
                # 添加 ±JITTER 随机抖动，防止多节点惊群
                import random

                jitter = delay * self.JITTER * (2 * random.random() - 1)
                delay = max(0.5, delay + jitter)

                logger.warning(
                    f"[FutuWatchdog] 🔌 连接断开 (连续失败 {self._consecutive_failures})，"  # noqa: E501
                    f"{delay:.1f}s 后尝试重连..."
                )

            # 4. 等待退避延迟
            await asyncio.sleep(delay)

            if not self._running:
                break

            # 5. 执行重连
            success = await self._do_reconnect()
            if success:
                self._last_reconnect_ts = time.monotonic()
                logger.info("[FutuWatchdog] ✅ 重连成功")
                self._consecutive_failures = 0
                self._last_success_ts = time.monotonic()
                FUTU_CONNECTION_STATUS.set(1)
            else:
                FUTU_RECONNECT_FAILURES.inc()
                logger.error(f"[FutuWatchdog] ❌ 重连失败 (第 {self._consecutive_failures} 次)")

    async def _health_check(self) -> bool:
        """
        健康检查：验证 Futu 连接是否活跃

        策略：
        1. 首先检查 status 标志
        2. 如果 status 显示连接，先确保探针标的已订阅，再获取快照
        3. 快照超时或异常 → 判定为不健康
        """
        # 快速路径：状态不是 CONNECTED
        if self._conn_mgr.status != "CONNECTED":
            return False

        if not self._conn_mgr.quote_ctx:
            return False

        # 深度检查：尝试获取探针标的快照
        try:
            from futu import RET_OK, SubType

            from backend.services.futu.utils import format_ticker

            probe_ticker = self.HEALTH_PROBE_SYMBOL
            market_ticker = format_ticker(probe_ticker)

            # 先订阅 QUOTE（get_stock_quote 的前置条件）
            try:
                # LRU 订阅池管理
                cache_mgr = self._futu.cache_mgr
                if not cache_mgr.has_topic(market_ticker, SubType.QUOTE):
                    evicted = cache_mgr.ensure_capacity(needed=1)
                    if evicted:
                        from .quote_handler import _execute_unsubscriptions
                        await _execute_unsubscriptions(self._conn_mgr, cache_mgr, evicted)

                    sub_ret, _ = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._conn_mgr.quote_ctx.subscribe,
                            [market_ticker],
                            [SubType.QUOTE],
                            subscribe_push=False,
                        ),
                        timeout=3.0,
                    )
                    if sub_ret == RET_OK:
                        cache_mgr.touch_topic(market_ticker, SubType.QUOTE)
                    else:
                        logger.debug("[FutuWatchdog] 探针订阅失败")
                        return False
            except Exception:
                return False

            ret, df = await asyncio.wait_for(
                asyncio.to_thread(self._conn_mgr.quote_ctx.get_stock_quote, [market_ticker]),
                timeout=self.HEALTH_TIMEOUT,
            )

            if ret != RET_OK:
                logger.debug(f"[FutuWatchdog] 健康探针失败: ret={ret}")
                return False

            if df is None or (hasattr(df, "empty") and df.empty):
                return False

            return True

        except asyncio.TimeoutError:
            logger.warning("[FutuWatchdog] 健康探针超时")
            return False
        except Exception as e:
            logger.debug(f"[FutuWatchdog] 健康检查异常: {e}")
            return False

    async def _do_reconnect(self) -> bool:
        """
        执行重连操作

        步骤：
        1. 关闭旧连接（安全清理）
        2. 重新建立连接
        3. 验证连接状态
        """
        try:
            logger.info("[FutuWatchdog] 正在执行重连...")

            # 1. 安全关闭旧连接
            try:
                self._futu.close()
            except Exception as e:
                logger.debug(f"[FutuWatchdog] 关闭旧连接时异常 (可忽略): {e}")

            # 2. 重新连接（在线程池中执行，防止阻塞事件循环）
            await asyncio.wait_for(
                asyncio.to_thread(self._futu.connect),
                timeout=10.0,
            )

            # 3. 验证连接结果
            if self._conn_mgr.status == "CONNECTED":
                logger.info("[FutuWatchdog] 重连验证通过")
                # 4. 恢复断连前的订阅（新 OpenQuoteContext 不继承旧订阅）
                await self._restore_subscriptions()
                return True
            else:
                error_msg = self._conn_mgr.error_msg or "未知错误"
                logger.warning(f"[FutuWatchdog] 重连后状态异常: {error_msg}")
                return False

        except asyncio.TimeoutError:
            logger.error("[FutuWatchdog] 重连超时 (10s)")
            return False
        except Exception as e:
            logger.error(f"[FutuWatchdog] 重连异常: {e}")
            return False

    async def _restore_subscriptions(self) -> None:
        """重连后恢复之前丢失的订阅"""
        from futu import RET_OK, SubType

        cache_mgr = self._futu.cache_mgr
        subscribed = cache_mgr.subscribed_topics  # 返回 set((ticker, sub_type_str))
        if not subscribed:
            return

        # 按 ticker 分组，批量订阅
        ticker_subs: dict = {}
        for ticker, sub_type_str in subscribed:
            ticker_subs.setdefault(ticker, []).append(sub_type_str)

        restored = 0
        for ticker, sub_type_strs in ticker_subs.items():
            try:
                # 将字符串转回 SubType 枚举
                futu_sub_types = [getattr(SubType, st, None) for st in sub_type_strs]
                futu_sub_types = [s for s in futu_sub_types if s is not None]
                if not futu_sub_types:
                    continue

                ret, _ = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._conn_mgr.quote_ctx.subscribe,
                        [ticker],
                        futu_sub_types,
                        subscribe_push=False,
                    ),
                    timeout=5.0,
                )
                if ret == RET_OK:
                    # 恢复成功后刷新 LRU 时间戳
                    for st in sub_type_strs:
                        cache_mgr.touch_topic(ticker, st)
                    restored += len(sub_type_strs)
                else:
                    logger.warning(f"[FutuWatchdog] 恢复订阅失败: {ticker} {sub_type_strs}")
            except Exception as e:
                logger.warning(f"[FutuWatchdog] 恢复订阅异常: {ticker}: {e}")

        if restored:
            logger.info(f"[FutuWatchdog] 已恢复 {restored} 个订阅 (池总量: {cache_mgr.subscription_count}/{cache_mgr.max_subscriptions})")

    def stop(self) -> None:
        """停止看门狗"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    @property
    def stats(self) -> dict:
        """返回看门狗运行统计（供 /health 端点使用）"""
        return {
            "running": self._running,
            "total_reconnects": self._total_reconnects,
            "consecutive_failures": self._consecutive_failures,
            "last_reconnect_ts": self._last_reconnect_ts,
            "last_success_ts": self._last_success_ts,
            "connection_status": self._conn_mgr.status,
        }


# ── 全局单例（延迟初始化）──────────────────────────────────────────
_watchdog: Optional[FutuWatchdog] = None


def get_watchdog(futu_svc=None) -> FutuWatchdog:
    """获取或创建看门狗单例"""
    global _watchdog
    if _watchdog is None:
        if futu_svc is None:
            from backend.services.futu import futu_service

            futu_svc = futu_service
        _watchdog = FutuWatchdog(futu_svc)
    return _watchdog
