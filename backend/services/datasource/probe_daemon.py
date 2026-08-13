"""
SVC-02: 三方服务可用性拨测 (Probe Daemon)
=========================================

周期性主动探活以下外部依赖, 将**成功率与延迟**写入 Prometheus metrics
(独立维度 ``quant_datasource_probe_*``), 并落库到 ``CallMetricsStore.probe_*``
(供 SVC-03 健康告警监控器消费):

- Futu OpenD       -> GET {futu_master.url}/health
- YFinance         -> GET {yf_primary.url}/health
- Finnhub          -> GET {finnhub_master.url}/health
- FMP              -> GET {fmp_master.url}/health
- FRED             -> GET {fred_master.url}/health
- OpenAI           -> LLMRouter.health_check()["primary"]
- Ollama           -> LLMRouter.health_check()["ollama"]

设计要点:
- 与业务调用维度解耦: ``DATASOURCE_AVAILABILITY`` 由真实业务 fetch 驱动, 业务流量
  为 0 时不刷新; ``DATASOURCE_PROBE_SUCCESS`` 由本 daemon 周期拨测驱动, 无流量也能
  反映源存活。
- 探针失败**不触达**业务限流退避/熔断器: 数据源探针直接 GET 节点 ``/health`` 端点
  (与 router 半开探针 _probe_node 同源), 既不读熔断状态也不写失败计数, 不施压已故障
  源、不污染业务熔断/退避状态机。仅反映「节点进程是否存活」, 不做真实 action 取数。
- LLM 探针 (openai/ollama) 走 LLMRouter.health_check, 与数据源探针隔离。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional

import httpx

from backend.core.metrics import (
    DATASOURCE_PROBE_FAILURES,
    DATASOURCE_PROBE_LATENCY,
    DATASOURCE_PROBE_SUCCESS,
    DATASOURCE_PROBE_TOTAL,
)
from backend.services.datasource.call_metrics_store import call_metrics

logger = logging.getLogger(__name__)


# 探针清单: 数据源探针 (node_key 定位 router 节点, 打 /health) | LLM 探针 ("openai"/"ollama")
@dataclass
class DataSourceProbe:
    name: str  # 指标 label (如 "finnhub" / "openai")
    kind: str  # "datasource" | "llm"
    node_key: str = ""  # 数据源探针对应的 router 节点名 (如 "futu_master"), 用于定位 /health URL
    action: str = ""  # 仅作 Prometheus latency 指标的 action label
    params: Optional[dict] = None


# node_key 必须与 DataSourceRouter._init_nodes 中的节点名严格一致
DEFAULT_PROBES: List[DataSourceProbe] = [
    DataSourceProbe("futu", "datasource", node_key="futu_master", action="quote"),
    DataSourceProbe("yfinance", "datasource", node_key="yf_primary", action="quote"),
    DataSourceProbe("finnhub", "datasource", node_key="finnhub_master", action="QUOTE"),
    DataSourceProbe("fmp", "datasource", node_key="fmp_master", action="quote"),
    DataSourceProbe("fred", "datasource", node_key="fred_master", action="MACRO_SERIES"),
    DataSourceProbe("openai", "llm"),
    DataSourceProbe("ollama", "llm"),
]


class DataSourceProbeDaemon:
    """周期性主动拨测三方服务, 刷新探针 Prometheus 指标 + call_metrics 探针字段。"""

    def __init__(
        self,
        probes: Optional[List[DataSourceProbe]] = None,
        interval_seconds: Optional[float] = None,
        node_health_fn: Optional[Callable[[str], Awaitable[bool]]] = None,
        llm_health_fn: Optional[Callable[[], Awaitable[Dict[str, bool]]]] = None,
    ):
        self.probes = probes or list(DEFAULT_PROBES)
        self.interval = float(
            interval_seconds if interval_seconds is not None else os.getenv("PROBE_INTERVAL_SECONDS", "60")
        )
        # 注入点 (测试用): 数据源探针默认走 _probe_node_health (GET 节点 /health)
        self._node_health_fn = node_health_fn
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
                # 数据源探针直接打节点 /health, 不写熔断/退避计数
                if self._node_health_fn is not None:
                    success = await self._node_health_fn(probe.node_key)
                else:
                    success = await self._probe_node_health(probe.node_key)
                status_label = "success" if success else "error"
                error_type = "none" if success else "network"
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

    async def _probe_node_health(self, node_key: str) -> bool:
        """对 router 中指定节点发起只读 /health 探测, 返回进程是否存活。

        与 router._probe_node 同源 (GET {node.url}/health), 但**不修改**节点状态
        (error_count/circuit_breaker_until/status), 纯只读探测, 不污染业务熔断/退避计数。
        仅在 router 未启用或节点不存在时返回 False。
        """
        if not node_key:
            return False
        from backend.services.datasource.router import data_source_router

        node = data_source_router._nodes.get(node_key)
        if node is None or not node.enabled:
            return False

        data_source_router._ensure_http_client()
        client = data_source_router._http_client
        if client is None:
            return False

        url = f"{node.url}/health"
        try:
            resp = await client.get(url, timeout=httpx.Timeout(5.0, connect=3.0))
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        try:
            body = resp.json()
            if isinstance(body, dict) and body.get("status") == "unhealthy":
                return False
        except Exception:
            pass
        return True

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
