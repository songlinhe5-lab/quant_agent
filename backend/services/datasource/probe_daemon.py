"""
SVC-02: 三方服务可用性拨测 (Probe Daemon)
=========================================

周期性主动探活以下外部依赖, 将**成功率与延迟**写入 Prometheus metrics
(独立维度 ``quant_datasource_probe_*``), 并落库到 ``CallMetricsStore.probe_*``
(供 SVC-03 健康告警监控器消费):

- Futu OpenD       -> datasource_registry.fetch("futu", "quote")
- YFinance         -> datasource_registry.fetch("yfinance", "quote")
- Finnhub          -> datasource_registry.fetch("finnhub", "QUOTE")
- FMP              -> datasource_registry.fetch("fmp", "quote")
- FRED             -> datasource_registry.fetch("fred", "MACRO_SERIES")
- OpenAI           -> LLMRouter.health_check()["primary"]
- Ollama           -> LLMRouter.health_check()["ollama"]

设计要点:
- 与业务调用维度解耦: ``DATASOURCE_AVAILABILITY`` 由真实业务 fetch 驱动, 业务流量
  为 0 时不刷新; ``DATASOURCE_PROBE_SUCCESS`` 由本 daemon 周期拨测驱动, 无流量也能
  反映源存活。
- 探针失败**不触达**业务限流退避/熔断器 (只发一次轻量探测, 不施压已故障源)。
- 探针 action 选用各源最轻量接口 (quote / macro_series), 避免重历史拉取。
- 离线环境: 各源 fetch 走 SVC-06 离线 stub / OFFLINE_MODE 短路, 探针自然返回成功,
  daemon 照常刷新探针指标 (无网络依赖)。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend.core.metrics import (
    DATASOURCE_PROBE_FAILURES,
    DATASOURCE_PROBE_LATENCY,
    DATASOURCE_PROBE_SUCCESS,
    DATASOURCE_PROBE_TOTAL,
)
from backend.services.datasource.call_metrics_store import call_metrics

logger = logging.getLogger(__name__)


# 探针清单: 数据源探针 (source, action, params) | LLM 探针 ("openai"/"ollama")
@dataclass
class DataSourceProbe:
    name: str  # 指标 label (如 "finnhub" / "openai")
    kind: str  # "datasource" | "llm"
    action: str = ""
    params: Optional[dict] = None


DEFAULT_PROBES: List[DataSourceProbe] = [
    DataSourceProbe("futu", "datasource", "quote", {"ticker": "AAPL"}),
    DataSourceProbe("yfinance", "datasource", "quote", {"ticker": "AAPL"}),
    DataSourceProbe("finnhub", "datasource", "QUOTE", {"symbol": "AAPL"}),
    DataSourceProbe("fmp", "datasource", "quote", {"symbol": "AAPL"}),
    DataSourceProbe("fred", "datasource", "MACRO_SERIES", {"series_id": "DGS10"}),
    DataSourceProbe("openai", "llm"),
    DataSourceProbe("ollama", "llm"),
]


class DataSourceProbeDaemon:
    """周期性主动拨测三方服务, 刷新探针 Prometheus 指标 + call_metrics 探针字段。"""

    def __init__(
        self,
        probes: Optional[List[DataSourceProbe]] = None,
        interval_seconds: Optional[float] = None,
        fetch_fn: Optional[Callable[[str, str, dict], Awaitable[Any]]] = None,
        llm_health_fn: Optional[Callable[[], Awaitable[Dict[str, bool]]]] = None,
    ):
        self.probes = probes or list(DEFAULT_PROBES)
        self.interval = float(
            interval_seconds if interval_seconds is not None else os.getenv("PROBE_INTERVAL_SECONDS", "60")
        )
        self._fetch_fn = fetch_fn  # 注入点 (测试用): 默认走 datasource_registry.fetch
        self._llm_health_fn = llm_health_fn  # 注入点 (测试用): 默认走 LLMRouter.health_check
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_results: Dict[str, bool] = {}

    # ------------------------------------------------------------------
    # 探针执行单元
    # ------------------------------------------------------------------
    async def _probe_one(self, probe: DataSourceProbe) -> bool:
        t0 = time.perf_counter()
        success = False
        error_type = "network"
        status_label = "error"
        try:
            if probe.kind == "llm":
                health = await self._get_llm_health()
                success = bool(health.get(probe.name, False))
                status_label = "success" if success else "error"
                error_type = "unreachable" if not success else "none"
            else:
                result = await self._do_fetch(probe.name, probe.action, probe.params or {})
                success = bool(getattr(result, "is_success", False))
                status_label = "success" if success else "error"
                err = getattr(result, "error", None)
                error_type = self._classify_error(err)
        except Exception as exc:  # 探针自身异常 -> 视为不可达
            success = False
            status_label = "error"
            error_type = "network"
            logger.warning("[Probe] %s 探针异常: %s", probe.name, exc)

        latency_ms = (time.perf_counter() - t0) * 1000.0

        # 1) 写入 call_metrics 探针字段 (供 SVC-03 健康告警消费)
        try:
            await call_metrics.record_probe(probe.name, success)
        except Exception as exc:  # 探针指标不可阻塞主循环
            logger.debug("[Probe] record_probe(%s) 失败: %s", probe.name, exc)

        # 2) 写入 Prometheus 探针指标 (独立维度)
        DATASOURCE_PROBE_SUCCESS.labels(source=probe.name).set(1 if success else 0)
        DATASOURCE_PROBE_LATENCY.labels(source=probe.name, action=probe.action or probe.kind).observe(latency_ms)
        DATASOURCE_PROBE_TOTAL.labels(source=probe.name, status=status_label).inc()
        if not success:
            DATASOURCE_PROBE_FAILURES.labels(source=probe.name, error_type=error_type).inc()

        self._last_results[probe.name] = success
        return success

    def _classify_error(self, err: Any) -> str:
        if err is None:
            return "none"
        err_code = str(getattr(err, "code", "") or "")
        msg = str(getattr(err, "message", "") or "").lower()
        if "rate" in msg or "429" in err_code or "402" in err_code:
            return "rate_limit"
        if "circuit" in msg or "CIRCUIT" in err_code:
            return "circuit_open"
        if "auth" in msg or "401" in err_code or "403" in err_code:
            return "auth"
        if "timeout" in msg:
            return "timeout"
        return "network"

    async def _do_fetch(self, source: str, action: str, params: dict) -> Any:
        if self._fetch_fn is not None:
            return await self._fetch_fn(source, action, params)
        from backend.services.datasource.source_registry import datasource_registry

        return await datasource_registry.fetch(source, action, params)

    async def _get_llm_health(self) -> Dict[str, bool]:
        if self._llm_health_fn is not None:
            return await self._llm_health_fn()
        from backend.services.ai_narrator.llm_service import llm_service

        return await llm_service.router.health_check()

    # ------------------------------------------------------------------
    # 周期循环
    # ------------------------------------------------------------------
    async def run_once(self) -> Dict[str, bool]:
        """执行一轮全部探针 (测试 / 手动触发用)。返回 {source: success}。"""
        results = await asyncio.gather(
            *(self._probe_one(p) for p in self.probes),
            return_exceptions=False,
        )
        return dict(zip((p.name for p in self.probes), results))

    async def _loop(self):
        self._running = True
        logger.info("[Probe] 拨测 daemon 启动, 周期 %.0fs, 探针 %d 个", self.interval, len(self.probes))
        while self._running:
            try:
                await self.run_once()
            except Exception as exc:
                logger.error("[Probe] 拨测循环异常: %s", exc)
            # 等待下一个周期 (可中断)
            for _ in range(int(self.interval)):
                if not self._running:
                    break
                await asyncio.sleep(1.0)

    async def start(self):
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


data_source_probe_daemon = DataSourceProbeDaemon()
