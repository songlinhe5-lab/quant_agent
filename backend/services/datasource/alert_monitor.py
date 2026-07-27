"""
==========================================
Rate Limit Alert Monitor (RL-11)
==========================================

代码层限流告警触发器：在 Throttler 的 on_rate_limit() 回调中实时检测
高危限流场景，主动推送飞书 Webhook 告警。

告警场景:
1. 限流频率飙升: 5 分钟内同一数据源限流 >10 次
2. 长时间退避: 退避时间 >2 分钟
3. 配额耗尽: category="quota_exhausted"
4. IP 封禁: category="ip_blocked"

架构:
- 由 Throttler.on_rate_limit() 调用 monitor.on_rate_limit_event()
- 告警通过 NotificationService 推送飞书 Webhook (复用 OBS-02)
- 内置去重冷却 (同数据源同类型 15 分钟内不重复告警)
"""

import asyncio
import time
from asyncio import Queue, QueueFull
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from backend.core.logger import logger


@dataclass
class RateLimitAlertEvent:
    """限流告警事件"""

    source: str
    category: str  # "rate_limit" | "quota_exhausted" | "ip_blocked"
    wait_seconds: float
    consecutive_rate_limits: int
    message: str
    severity: str  # "critical" | "warning"


class RateLimitAlertMonitor:
    """
    RL-11: 限流告警监控器。

    实时检测高危限流场景并通过飞书 Webhook 推送告警。
    内置去重冷却机制，防止告警风暴。
    """

    # 告警阈值
    SPIKE_WINDOW_SECONDS = 300  # 5 分钟窗口
    SPIKE_THRESHOLD = 10  # 5 分钟内 >10 次触发
    LONG_BACKOFF_THRESHOLD = 120  # 退避 >2 分钟

    # 去重冷却: 同数据源+同类型 15 分钟内不重复告警
    COOLDOWN_SECONDS = 900

    def __init__(self):
        self._rate_counts: Dict[str, list] = {}  # source -> [timestamps]
        self._last_alert: Dict[Tuple[str, str], float] = {}  # (source, alert_type) -> timestamp
        self._notification_service = None  # 延迟导入
        self._queue: Optional[Queue] = None  # 异步告警队列 (lifespan startup 时创建)
        self._consumer_task: Optional[asyncio.Task] = None  # 后台消费 task
        self._started = False

    def _get_notification_service(self):
        """延迟导入 NotificationService（避免循环依赖）"""
        if self._notification_service is None:
            try:
                from backend.services.notification_service import notification_service

                self._notification_service = notification_service
            except ImportError:
                pass
        return self._notification_service

    def on_rate_limit_event(
        self,
        source: str,
        category: str,
        wait_seconds: float,
        consecutive_rate_limits: int,
    ) -> Optional[RateLimitAlertEvent]:
        """
        处理限流事件，检测是否需要触发告警。

        Args:
            source: 数据源名称
            category: 错误分类 ("rate_limit" / "quota_exhausted" / "ip_blocked")
            wait_seconds: 退避等待秒数
            consecutive_rate_limits: 连续限流次数

        Returns:
            触发告警时返回 RateLimitAlertEvent，否则返回 None
        """
        now = time.time()
        alert = None

        # 1. 记录限流事件时间戳 (用于频率飙升检测)
        if source not in self._rate_counts:
            self._rate_counts[source] = []
        self._rate_counts[source].append(now)
        # 清理过期时间戳
        cutoff = now - self.SPIKE_WINDOW_SECONDS
        self._rate_counts[source] = [ts for ts in self._rate_counts[source] if ts > cutoff]

        # 2. 检测告警场景 (按优先级)

        # 场景 A: IP 封禁 (最严重，立即告警)
        if category == "ip_blocked":
            alert = self._try_create_alert(
                source,
                "ip_blocked",
                severity="critical",
                message=f"🚨 数据源 [{source}] IP 被封禁！退避 {wait_seconds:.0f}s，请立即检查 IP 状态",
            )

        # 场景 B: 配额耗尽
        elif category == "quota_exhausted":
            alert = self._try_create_alert(
                source,
                "quota_exhausted",
                severity="critical",
                message=f"🚨 数据源 [{source}] API 配额已耗尽！退避 {wait_seconds:.0f}s，请检查 API Key 配额",
            )

        # 场景 C: 长时间退避 (>2min)
        elif wait_seconds > self.LONG_BACKOFF_THRESHOLD:
            alert = self._try_create_alert(
                source,
                "long_backoff",
                severity="warning",
                message=f"⚠️ 数据源 [{source}] 退避时间过长: {wait_seconds:.0f}s (>2min)，数据源可能已被长时间封禁",
            )

        # 场景 D: 限流频率飙升 (5min >10 次)
        elif len(self._rate_counts[source]) > self.SPIKE_THRESHOLD:
            alert = self._try_create_alert(
                source,
                "rate_limit_spike",
                severity="critical",
                message=(
                    f"🚨 数据源 [{source}] 限流频率飙升: "
                    f"过去 5 分钟内触发 {len(self._rate_counts[source])} 次 (>10)，"
                    f"连续限流 {consecutive_rate_limits} 次"
                ),
            )

        # 3. 如果触发了告警，投递到异步队列（非阻塞）
        if alert is not None:
            self._enqueue_alert(alert)

        return alert

    def _try_create_alert(
        self,
        source: str,
        alert_type: str,
        severity: str,
        message: str,
    ) -> Optional[RateLimitAlertEvent]:
        """尝试创建告警事件（去重冷却检查）"""
        now = time.time()
        key = (source, alert_type)

        # 去重: 同数据源+同类型在冷却期内不重复告警
        last_time = self._last_alert.get(key, 0)
        if now - last_time < self.COOLDOWN_SECONDS:
            logger.debug(
                f"[RL-11] 告警去重: {source}/{alert_type} "
                f"(距上次告警 {now - last_time:.0f}s < {self.COOLDOWN_SECONDS}s)"
            )
            return None

        self._last_alert[key] = now
        return RateLimitAlertEvent(
            source=source,
            category=alert_type,
            wait_seconds=0,
            consecutive_rate_limits=0,
            message=message,
            severity=severity,
        )

    def _enqueue_alert(self, alert: RateLimitAlertEvent):
        """将告警投递到异步队列（同步、非阻塞，可在 sync 限流回调中安全调用）。

        后台 consumer task 在 lifespan 启动后持续消费队列并推送飞书 Webhook，
        从而完全解耦「告警触发」（限流回调热路径）与「网络 IO 推送」，
        避免限流回调被飞书 Webhook 的网络延迟阻塞。
        """
        notification_svc = self._get_notification_service()
        if notification_svc is None:
            logger.warning(f"[RL-11] 告警触发但 NotificationService 不可用: {alert.message}")
            return

        # 后台消费器未启动（无事件循环上下文）：降级为同步发送，保证告警不丢
        if self._queue is None:
            try:
                asyncio.run(notification_svc.send_alert(alert.message))
                logger.warning(f"[RL-11] 告警已推送(降级同步): [{alert.severity}] {alert.message}")
            except RuntimeError:
                logger.warning(f"[RL-11] 告警无法推送 (监控器未启动且无事件循环): {alert.message}")
            return

        # 已启动：非阻塞入队，由后台 consumer 异步发送（不阻塞限流回调）
        try:
            self._queue.put_nowait(alert)
        except QueueFull:
            logger.warning(f"[RL-11] 告警队列已满，丢弃: {alert.message}")

    async def start(self):
        """启动后台消费 task。必须在事件循环内调用（app lifespan startup）。

        幂等：重复调用不会创建多个 consumer。
        """
        if self._started:
            return
        self._queue = Queue()
        self._consumer_task = asyncio.create_task(self._consume())
        self._started = True
        logger.info("[RL-11] 限流告警后台消费器已启动")

    async def stop(self):
        """停止后台消费 task（app lifespan shutdown）。幂等且可安全重复调用。"""
        self._started = False
        task = self._consumer_task
        self._consumer_task = None
        self._queue = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("[RL-11] 限流告警后台消费器已停止")

    async def _consume(self):
        """后台消费协程：从队列取告警并推送飞书 Webhook。"""
        queue = self._queue
        assert queue is not None
        while True:
            alert = await queue.get()
            try:
                svc = self._get_notification_service()
                if svc is None:
                    logger.warning(f"[RL-11] 告警丢弃 (NotificationService 不可用): {alert.message}")
                else:
                    await svc.send_alert(alert.message)
                    logger.warning(f"[RL-11] 告警已推送: [{alert.severity}] {alert.message}")
            except Exception as e:
                logger.error(f"[RL-11] 告警推送异常: {e}", alert=alert.message)
            finally:
                queue.task_done()

    def get_status(self) -> dict:
        """获取监控器当前状态（用于调试/可观测性）"""
        active_spike_sources = [
            source for source, timestamps in self._rate_counts.items() if len(timestamps) > self.SPIKE_THRESHOLD
        ]
        return {
            "active_spike_sources": active_spike_sources,
            "recent_rate_counts": {source: len(timestamps) for source, timestamps in self._rate_counts.items()},
            "cooldown_keys": list(self._last_alert.keys()),
        }

    def reset(self):
        """重置监控器状态（用于测试）"""
        self._rate_counts.clear()
        self._last_alert.clear()


# 全局单例
rate_limit_alert_monitor = RateLimitAlertMonitor()
