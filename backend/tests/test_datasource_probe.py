"""
SVC-02: 三方服务可用性拨测测试
==============================

验证 DataSourceProbeDaemon:
- 周期探活各源 (datasource + llm) 并写入独立探针 Prometheus 指标
  (quant_datasource_probe_*), 与业务调用维度 (quant_datasource_*) 解耦
- 探针结果落 call_metrics.record_probe (供 SVC-03 健康告警消费)
- 数据源探针直连节点 /health (不写熔断/退避计数), 失败统一归 network;
  LLM 探针失败归 unreachable

测试通过注入 node_health_fn / llm_health_fn 控制底层结果, 真实驱动 daemon 循环逻辑
(与 SVC-07 混沌测试同一"只注入底层故障"硬标准)。Prometheus 指标为进程级单例,
各用例使用唯一 source 标签以避免 Counter 跨用例累积干扰断言, 并通过
REGISTRY.get_sample_value 读取指定 label 的当前值。
"""

import asyncio
import os
import sys
import unittest.mock as mock

import pytest
from prometheus_client import REGISTRY

os.environ.setdefault("QUANT_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.services.datasource.call_metrics_store import call_metrics  # noqa: E402
from backend.services.datasource.probe_daemon import (  # noqa: E402
    DataSourceProbe,
    DataSourceProbeDaemon,
)


def _g(metric_name: str, **labels) -> float:
    val = REGISTRY.get_sample_value(metric_name, labels)
    return val if val is not None else 0.0


def _ds_probe(name, node_key="futu_master", action="quote"):
    return DataSourceProbe(name, "datasource", node_key=node_key, action=action)


@pytest.fixture
def patched_record_probe():
    with mock.patch.object(call_metrics, "record_probe", new=mock.AsyncMock()) as m:
        yield m


def test_probe_success_writes_metrics(patched_record_probe):
    node_health_fn = mock.AsyncMock(return_value=True)
    llm_health_fn = mock.AsyncMock(return_value={"ok_openai": True, "ok_ollama": True})

    daemon = DataSourceProbeDaemon(
        probes=[
            _ds_probe("ok_finnhub", node_key="finnhub_master", action="QUOTE"),
            _ds_probe("ok_yfinance", node_key="yf_primary", action="quote"),
            DataSourceProbe("ok_openai", "llm"),
            DataSourceProbe("ok_ollama", "llm"),
        ],
        node_health_fn=node_health_fn,
        llm_health_fn=llm_health_fn,
    )
    results = asyncio.run(daemon.run_once())

    assert results == {"ok_finnhub": True, "ok_yfinance": True, "ok_openai": True, "ok_ollama": True}
    for src in ("ok_finnhub", "ok_yfinance", "ok_openai", "ok_ollama"):
        assert _g("quant_datasource_probe_success", source=src) == 1.0
        assert _g("quant_datasource_probe_total", source=src, status="success") == 1.0
    assert patched_record_probe.await_count == 4
    patched_record_probe.assert_any_await("ok_finnhub", True)
    # 数据源探针应调用 node_health_fn 且传入正确的 node_key
    node_health_fn.assert_any_await("finnhub_master")
    node_health_fn.assert_any_await("yf_primary")


def test_probe_failure_network_for_datasource(patched_record_probe):
    node_health_fn = mock.AsyncMock(return_value=False)
    llm_health_fn = mock.AsyncMock(return_value={"err_openai": False, "err_ollama": True})

    daemon = DataSourceProbeDaemon(
        probes=[
            _ds_probe("err_finnhub", node_key="finnhub_master", action="QUOTE"),
            DataSourceProbe("err_openai", "llm"),
            DataSourceProbe("err_ollama", "llm"),
        ],
        node_health_fn=node_health_fn,
        llm_health_fn=llm_health_fn,
    )
    results = asyncio.run(daemon.run_once())

    assert results["err_finnhub"] is False
    assert results["err_openai"] is False
    assert results["err_ollama"] is True

    assert _g("quant_datasource_probe_success", source="err_finnhub") == 0.0
    assert _g("quant_datasource_probe_success", source="err_openai") == 0.0
    assert _g("quant_datasource_probe_success", source="err_ollama") == 1.0

    assert _g("quant_datasource_probe_total", source="err_finnhub", status="error") == 1.0
    # 数据源探针失败统一归 network, 不再有 rate_limit/circuit_open 等业务错误分类
    assert _g("quant_datasource_probe_failures_total", source="err_finnhub", error_type="network") == 1.0
    assert _g("quant_datasource_probe_failures_total", source="err_openai", error_type="unreachable") == 1.0

    patched_record_probe.assert_any_await("err_finnhub", False)


def test_probe_node_health_fn_exception_treated_unreachable(patched_record_probe):
    node_health_fn = mock.AsyncMock(side_effect=RuntimeError("connection refused"))
    daemon = DataSourceProbeDaemon(
        probes=[_ds_probe("ex_fred", node_key="fred_master", action="MACRO_SERIES")],
        node_health_fn=node_health_fn,
        llm_health_fn=mock.AsyncMock(return_value={}),
    )
    results = asyncio.run(daemon.run_once())
    assert results["ex_fred"] is False
    assert _g("quant_datasource_probe_success", source="ex_fred") == 0.0
    assert _g("quant_datasource_probe_failures_total", source="ex_fred", error_type="network") == 1.0
