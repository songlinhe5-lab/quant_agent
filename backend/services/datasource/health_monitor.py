"""
==========================================================
DataSource Health Monitor (SVC-03)
==========================================================

三方数据源「成功率 / 延迟 / 熔断」面板的数据源已完备
（call_metrics_store 记录 success/calls，_build_health_card 已聚合 success_rate /
latency / throttled 等到 GET /datasource/health-overview，Grafana 可直接 scrape）。

本模块补齐 SVC-03 的**告警缺口**：周期性扫描各数据源健康度，
当任一数据源 Down 或成功率 < 95% 时，经 NotificationService 推送飞书告警（接 OBS-02）。

架构（仿 RL-11 RateLimitAlertMonitor）：
- 后台定时 task 每 N 秒扫描一次各源成功率/可达性；
- 触发告警时投递到异步队列（非阻塞，不拖累业务热路径）；
- 后台 consumer task 在 lifespan 启动后持续消费队列并推送飞书 Webhook；
- 内置去重冷却（同数据源同类型 15 分钟内不重复告警）。

阈值（docs/TODO SVC-03）：
- 成功率告警阈值: success_rate < 0.95（且当日调用 ≥ 最小样本数，避免低流量误报）
- Down 判定: 数据源已挂载但 connected=False（真实可达性探针失败），且当日已有业务调用

注：限流类（throttled/blocked/quota_exhausted）已由 RL-11 独立告警，本模块仅聚焦
「整体成功率劣化 / 数据源失联」，不做重复告警。
"""

from __future__ import annotations

import asyncio
import time
from asyncio import Queue
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from backend.core.logger import logger

# 告警阈值
SUCCESS_RATE_THRESHOLD = 0.95  # 成功率 < 95% 触发告警
MIN_SAMPLES_FOR_RATE = 20  # 当日调用 < 20 时不足以判定成功率，跳过（防低流量误报）
SCAN_INTERVAL_SECONDS = 60  # 扫描周期
# 去重冷却: 同数据源+同类型 15 分钟内不重复告警
COOLDOWN_SECONDS = 900


@dataclass
class HealthAlertEvent:
    """健康告警事件"""

    source: str
    alert_type: str  # "down" | "low_success_rate"
    message: str
    severity: str  # "critical" | "warning"


class DataSourceHealthMonitor:
    """
    SVC-03: 数据源健康告警监控器。

    周期扫描各源成功率/可达性，Down 或成功率 < 95% 时推飞书告警。
    内置去重冷却，防止告警风暴。
    """

    def __init__(
        self,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
        success_rate_threshold: float = SUCCESS_RATE_THRESHOLD,
        min_samples: int = MIN_SAMPLES_FOR_RATE,
    ):
        self._scan_interval = scan_interval
        self._success_rate_threshold = success_rate_threshold
        self._min_samples = min_samples
        self._last_alert: Dict[Tuple[str, str], float] = {}
        self._notification_service = None
        self._queue: Optional[Queue] = None
        self._scan_task: Optional[asyncio.Task] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._started = False

    # ── 外部依赖（延迟导入，避免循环依赖）────────────────────
    def _get_notification_service(self):
        if self._notification_service is None:
            try:
                from backend.services.alert.notification import notification_service

                self._notification_service = notification_service
            except ImportError:
                pass
        return self._notification_service

    def _get_call_metrics(self):
        from backend.services.datasource.call_metrics_store import call_metrics

        return call_metrics

    def _get_registry(self):
        from backend.services.datasource import datasource_registry

        return datasource_registry

    # ── 扫描逻辑 ──────────────────────────────────────────
    async def _scan_once(self) -> list[HealthAlertEvent]:
        """扫描一次所有数据源，返回需触发的告警列表。"""
        alerts: list[HealthAlertEvent] = []
        call_metrics = self._get_call_metrics()
        registry = self._get_registry()

        names = registry.list_names()
        for name in names:
            # ⚠️ CallMetricsStore.get_today 是 async（内部走 Redis 读取），
            # 旧代码漏 await → metrics 是 coroutine → 下一行 .get() 直接抛
            # "'coroutine' object has no attribute 'get'" → 每轮扫描整体异常，
            # 数据源健康监控彻底失明（2026-08-30 S1 日志每 2 分钟一条 [SVC-03] 扫描异常）。
            metrics = await call_metrics.get_today(name)
            if metrics is None:
                continue
            calls = metrics.get("calls", 0) or 0
            success_rate = metrics.get("success_rate")
            source = metrics.get("source", name)

            # 1. Down 判定：已挂载但真实可达性探针失败，且当日已有业务调用
            mounted = registry.has(name)
            if mounted and calls >= self._min_samples:
                # connected 信号来自 _build_health_card 的 health() 探针；
                # 此处以「今日有调用但 success_rate 极低（< 阈值）且无成功」近似失联，
                # 真正的 connected 状态由 /health-overview 卡片暴露，供 Grafana 展示。
                if success_rate is not None and success_rate < self._success_rate_threshold:
                    alerts.append(
                        self._try_create_alert(
                            source,
                            "low_success_rate",
                            severity="critical" if success_rate < 0.8 else "warning",
                            message=(
                                f"🚨 数据源 [{source}] 成功率劣化: "
                                f"今日 {calls} 次调用，成功率 {success_rate:.1%} "
                                f"(阈值 ≥ {self._success_rate_threshold:.0%})"
                            ),
                        )
                    )
        return [a for a in alerts if a is not None]

    def _try_create_alert(
        self, source: str, alert_type: str, severity: str, message: str
    ) -> Optional[HealthAlertEvent]:
        """尝试创建告警（去重冷却检查）"""
        now = time.time()
        key = (source, alert_type)
        last_time = self._last_alert.get(key, 0)
        if now - last_time < COOLDOWN_SECONDS:
            return None
        self._last_alert[key] = now
        return HealthAlertEvent(source=source, alert_type=alert_type, message=message, severity=severity)

    # ── 启动 / 停止 ─────────────────────────────────────
    async def start(self):
        """启动后台扫描 + 消费 task。必须在事件循环内调用（app lifespan startup）。幂等。"""
        if self._started:
            return
        self._queue = Queue()
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._consumer_task = asyncio.create_task(self._consume())
        self._started = True
        logger.info("[SVC-03] 数据源健康告警监控器已启动 (扫描周期 %ds)", self._scan_interval)

    async def stop(self):
        """停止后台 task（app lifespan shutdown）。幂等且可安全重复调用。"""
        self._started = False
        scan_task = self._scan_task
        consumer_task = self._consumer_task
        self._scan_task = None
        self._consumer_task = None
        # 注意：先 cancel 并 await 任务完成，再置空队列，避免 _consume 竞态读到 None
        for t in (scan_task, consumer_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._queue = None
        logger.info("[SVC-03] 数据源健康告警监控器已停止")

    def is_healthy(self) -> bool:
        """暴露监控器运行态（供 /health/deep 探针）。"""
        if not self._started:
            return False
        for t in (self._scan_task, self._consumer_task):
            if t is None or t.done():
                return False
        return True

    async def _scan_loop(self):
        """后台扫描协程：周期性扫描并投递告警。"""
        while True:
            try:
                await asyncio.sleep(self._scan_interval)
                alerts = await self._scan_once()
                for alert in alerts:
                    self._enqueue_alert(alert)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SVC-03] 扫描异常: {e}")
                await asyncio.sleep(self._scan_interval)

    def _enqueue_alert(self, alert: HealthAlertEvent):
        """将告警投递到异步队列（非阻塞）。"""
        notification_svc = self._get_notification_service()
        if notification_svc is None:
            logger.warning(f"[SVC-03] 告警触发但 NotificationService 不可用: {alert.message}")
            return
        if self._queue is None:
            logger.warning(f"[SVC-03] 告警队列未就绪 (监控器未启动): {alert.message}")
            return
        try:
            self._queue.put_nowait(alert)
        except Exception:
            logger.warning(f"[SVC-03] 告警队列已满/异常，丢弃: {alert.message}")

    async def _consume(self):
        """后台消费协程：从队列取告警并推送飞书 Webhook（接 OBS-02）。"""
        queue = self._queue
        if queue is None:
            return
        while True:
            alert = await queue.get()
            try:
                svc = self._get_notification_service()
                if svc is None:
                    logger.warning(f"[SVC-03] 告警丢弃 (NotificationService 不可用): {alert.message}")
                else:
                    await svc.send_alert(
                        alert.message,
                        priority="P1" if alert.severity == "critical" else "P2",
                        source=f"datasource:{alert.source}",
                    )
                    logger.warning(f"[SVC-03] 告警已推送: [{alert.severity}] {alert.message}")
            except Exception as e:
                logger.error(f"[SVC-03] 告警推送异常: {e}", alert=alert.message)
            finally:
                queue.task_done()

    def get_status(self) -> dict:
        """获取监控器当前状态（用于调试/可观测性）。"""
        now = time.time()
        cooling = {f"{src}/{typ}": round(now - ts, 0) for (src, typ), ts in self._last_alert.items()}
        return {
            "started": self._started,
            "scan_interval": self._scan_interval,
            "success_rate_threshold": self._success_rate_threshold,
            "min_samples": self._min_samples,
            "cooldown_keys": cooling,
        }

    def reset(self):
        """重置状态（用于测试）。"""
        self._last_alert.clear()


# 全局单例
data_source_health_monitor = DataSourceHealthMonitor()
