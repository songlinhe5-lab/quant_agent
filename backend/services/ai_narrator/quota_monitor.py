"""
==========================================================
配额与成本监控器 (SVC-05)
==========================================================

量化主脑重度依赖两类「带配额 / 计费」的外部资源：
1. LLM（OpenAI / DeepSeek 等）—— 按 token 计费，多数套餐有每日 / 每月硬配额；
2. Finnhub / FMP 等行情源 —— 有每日 API 调用配额，超限即硬停服。

SVC-03 的 DataSourceHealthMonitor 聚焦「成功率 / 失联」，
本模块补齐 **配额与成本** 维度的告警缺口：
- LLM 当日 token 消耗逼近预算上限（默认阈值 80% 警告 / 100% 严重）；
- Finnhub 当日配额耗尽（硬停服，立即 critical 告警）。

架构（仿 SVC-03 DataSourceHealthMonitor）：
- 后台定时 task 每 N 秒扫描一次；
- 触发告警时投递到异步队列（非阻塞，不拖累业务热路径）；
- 后台 consumer task 持续消费队列并推送飞书 Webhook（接 OBS-02）；
- 内置去重冷却（同类型 15 分钟内不重复告警）。

阈值（docs/TODO SVC-05）：
- LLM 预算告警阈值: LLM_DAILY_TOKEN_BUDGET > 0 时启用；
  达 80% 触发 warning，达 100% 触发 critical。
- Finnhub 配额耗尽: 当日 quota_exhausted > 0 即 critical（硬停服）。
"""

from __future__ import annotations

import asyncio
import os
import time
from asyncio import Queue
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from backend.core.logger import logger

# 告警阈值
LLM_TOKEN_WARN_RATIO = 0.80  # 预算消耗达 80% 警告
LLM_TOKEN_CRIT_RATIO = 1.00  # 预算消耗达 100% 严重
SCAN_INTERVAL_SECONDS = 60  # 扫描周期
COOLDOWN_SECONDS = 900  # 去重冷却: 同类型 15 分钟内不重复告警

# LLM 每日 token 预算（None/0 = 不启用预算告警）
LLM_DAILY_TOKEN_BUDGET = int(os.getenv("LLM_DAILY_TOKEN_BUDGET", "0") or "0")


@dataclass
class QuotaAlertEvent:
    """配额/成本告警事件"""

    alert_type: str  # "llm_token_budget" | "finnhub_quota_exhausted"
    message: str
    severity: str  # "critical" | "warning"


class QuotaCostMonitor:
    """
    SVC-05: 配额与成本监控器。

    周期扫描 LLM token 预算逼近度 + Finnhub 配额耗尽，触发飞书告警。
    内置去重冷却，防止告警风暴。
    """

    def __init__(
        self,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
        llm_daily_budget: int = LLM_DAILY_TOKEN_BUDGET,
    ):
        self._scan_interval = scan_interval
        self._llm_daily_budget = llm_daily_budget
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

    def _get_token_store(self):
        from backend.services.ai_narrator.token_usage_store import token_usage_store

        return token_usage_store

    def _get_call_metrics(self):
        from backend.services.datasource.call_metrics_store import call_metrics

        return call_metrics

    # ── 扫描逻辑 ──────────────────────────────────────────
    async def _scan_once(self) -> list[QuotaAlertEvent]:
        """扫描一次所有配额维度，返回需触发的告警列表。"""
        alerts: list[QuotaAlertEvent] = []

        # 1. LLM token 预算逼近
        if self._llm_daily_budget and self._llm_daily_budget > 0:
            store = self._get_token_store()
            today = await store.get_today()
            used = today.get("total_tokens", 0) or 0
            if used > 0:
                ratio = used / self._llm_daily_budget
                if ratio >= LLM_TOKEN_CRIT_RATIO:
                    alerts.append(
                        self._try_create_alert(
                            "llm",
                            "llm_token_budget",
                            severity="critical",
                            message=(
                                f"🚨 LLM 每日 token 预算耗尽: 已用 {used:,} / 预算 "
                                f"{self._llm_daily_budget:,} ({ratio:.0%})，已达上限，"
                                f"后续调用将失败或触发降级"
                            ),
                        )
                    )
                elif ratio >= LLM_TOKEN_WARN_RATIO:
                    alerts.append(
                        self._try_create_alert(
                            "llm",
                            "llm_token_budget",
                            severity="warning",
                            message=(
                                f"⚠️ LLM 每日 token 预算逼近: 已用 {used:,} / 预算 "
                                f"{self._llm_daily_budget:,} ({ratio:.0%})，"
                                f"剩余 {self._llm_daily_budget - used:,}"
                            ),
                        )
                    )

        # 2. Finnhub 配额耗尽（硬停服）
        call_metrics = self._get_call_metrics()
        finnhub = await call_metrics.get_today("finnhub")
        if finnhub is not None:
            rl_breakdown = finnhub.get("rl_breakdown") or {}
            quota_exhausted = rl_breakdown.get("quota_exhausted", 0) or 0
            if quota_exhausted > 0:
                alerts.append(
                    self._try_create_alert(
                        "finnhub",
                        "finnhub_quota_exhausted",
                        severity="critical",
                        message=(
                            f"🚨 Finnhub 当日配额已耗尽 {quota_exhausted} 次，"
                            f"行情源硬停服，请检查 FMP / 辅节点兜底或升级套餐"
                        ),
                    )
                )

        return [a for a in alerts if a is not None]

    def _try_create_alert(self, source: str, alert_type: str, severity: str, message: str) -> Optional[QuotaAlertEvent]:
        """尝试创建告警（去重冷却检查）"""
        now = time.time()
        key = (source, alert_type)
        last_time = self._last_alert.get(key, 0)
        if now - last_time < COOLDOWN_SECONDS:
            return None
        self._last_alert[key] = now
        return QuotaAlertEvent(alert_type=alert_type, message=message, severity=severity)

    # ── 启动 / 停止 ─────────────────────────────────────
    async def start(self):
        """启动后台扫描 + 消费 task。必须在事件循环内调用（app lifespan startup）。幂等。"""
        if self._started:
            return
        self._queue = Queue()
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._consumer_task = asyncio.create_task(self._consume())
        self._started = True
        logger.info(
            "[SVC-05] 配额与成本监控器已启动 (周期 %ds, LLM预算 %d)",
            self._scan_interval,
            self._llm_daily_budget,
        )

    async def stop(self):
        """停止后台 task（app lifespan shutdown）。幂等且可安全重复调用。"""
        self._started = False
        scan_task = self._scan_task
        consumer_task = self._consumer_task
        self._scan_task = None
        self._consumer_task = None
        # 先 cancel 并 await 任务完成，再置空队列，避免 _consume 竞态读到 None
        for t in (scan_task, consumer_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        self._queue = None
        logger.info("[SVC-05] 配额与成本监控器已停止")

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
                logger.error(f"[SVC-05] 扫描异常: {e}")
                await asyncio.sleep(self._scan_interval)

    def _enqueue_alert(self, alert: QuotaAlertEvent):
        """将告警投递到异步队列（非阻塞）。"""
        notification_svc = self._get_notification_service()
        if notification_svc is None:
            logger.warning(f"[SVC-05] 告警触发但 NotificationService 不可用: {alert.message}")
            return
        if self._queue is None:
            logger.warning(f"[SVC-05] 告警队列未就绪 (监控器未启动): {alert.message}")
            return
        try:
            self._queue.put_nowait(alert)
        except Exception:
            logger.warning(f"[SVC-05] 告警队列已满/异常，丢弃: {alert.message}")

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
                    logger.warning(f"[SVC-05] 告警丢弃 (NotificationService 不可用): {alert.message}")
                else:
                    await svc.send_alert(
                        alert.message,
                        priority="P1" if alert.severity == "critical" else "P2",
                        source=f"quota:{alert.alert_type}",
                    )
                    logger.warning(f"[SVC-05] 告警已推送: [{alert.severity}] {alert.message}")
            except Exception as e:
                logger.error(f"[SVC-05] 告警推送异常: {e}", alert=alert.message)
            finally:
                queue.task_done()

    def get_status(self) -> dict:
        """获取监控器当前状态（用于调试/可观测性）。"""
        now = time.time()
        cooling = {f"{src}/{typ}": round(now - ts, 0) for (src, typ), ts in self._last_alert.items()}
        return {
            "started": self._started,
            "scan_interval": self._scan_interval,
            "llm_daily_budget": self._llm_daily_budget,
            "cooldown_keys": cooling,
        }

    def reset(self):
        """重置状态（用于测试）。"""
        self._last_alert.clear()


# 全局单例
quota_cost_monitor = QuotaCostMonitor()
