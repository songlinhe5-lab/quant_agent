"""
SVC-02: 三方服务可用性拨测测试
==============================

验证 DataSourceProbeDaemon:
- 周期探活各源 (datasource + llm) 并写入独立探针 Prometheus 指标
  (quant_datasource_probe_*), 与业务调用维度 (quant_datasource_*) 解耦
- 探针结果落 call_metrics.record_probe (供 SVC-03 健康告警消费)
- 失败分类 (rate_limit / circuit_open / auth / timeout / network)

测试通过注入 fetch_fn / llm_health_fn 控制底层结果, 真实驱动 daemon 循环逻辑
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


class _FakeResult:
    """模拟 datasource_registry.fetch 返回的 Result。"""

    def __init__(self, success: bool, code: str = "", message: str = ""):
        self.is_success = success
        self.error = None if success or not code else type("E", (), {"code": code, "message": message})()


def _ds_probe(name, action="QUOTE", params=None):
    return DataSourceProbe(name, "datasource", action, params or {"symbol": "AAPL"})


@pytest.fixture
def patched_record_probe():
    with mock.patch.object(call_metrics, "record_probe", new=mock.AsyncMock()) as m:
        yield m


def test_probe_success_writes_metrics(patched_record_probe):
    fetch_fn = mock.AsyncMock(return_value=_FakeResult(True))
    llm_health_fn = mock.AsyncMock(return_value={"ok_openai": True, "ok_ollama": True})

    daemon = DataSourceProbeDaemon(
        probes=[
            _ds_probe("ok_finnhub", action="QUOTE"),
            _ds_probe("ok_yfinance", action="quote"),
            DataSourceProbe("ok_openai", "llm"),
            DataSourceProbe("ok_ollama", "llm"),
        ],
        fetch_fn=fetch_fn,
        llm_health_fn=llm_health_fn,
    )
    results = asyncio.run(daemon.run_once())

    assert results == {"ok_finnhub": True, "ok_yfinance": True, "ok_openai": True, "ok_ollama": True}
    for src in ("ok_finnhub", "ok_yfinance", "ok_openai", "ok_ollama"):
        assert _g("quant_datasource_probe_success", source=src) == 1.0
        assert _g("quant_datasource_probe_total", source=src, status="success") == 1.0
    assert patched_record_probe.await_count == 4
    patched_record_probe.assert_any_await("ok_finnhub", True)


def test_probe_failure_classifies_error(patched_record_probe):
    fetch_fn = mock.AsyncMock(return_value=_FakeResult(False, "RATE_LIMIT", "rate limited 429"))
    llm_health_fn = mock.AsyncMock(return_value={"err_openai": False, "err_ollama": True})

    daemon = DataSourceProbeDaemon(
        probes=[
            _ds_probe("err_finnhub", action="QUOTE"),
            DataSourceProbe("err_openai", "llm"),
            DataSourceProbe("err_ollama", "llm"),
        ],
        fetch_fn=fetch_fn,
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
    assert _g("quant_datasource_probe_failures_total", source="err_finnhub", error_type="rate_limit") == 1.0
    assert _g("quant_datasource_probe_failures_total", source="err_openai", error_type="unreachable") == 1.0

    patched_record_probe.assert_any_await("err_finnhub", False)


def test_probe_circuit_open_classification(patched_record_probe):
    fetch_fn = mock.AsyncMock(return_value=_FakeResult(False, "CIRCUIT_OPEN", "circuit open"))
    daemon = DataSourceProbeDaemon(
        probes=[_ds_probe("cb_futu", action="quote")],
        fetch_fn=fetch_fn,
        llm_health_fn=mock.AsyncMock(return_value={}),
    )
    asyncio.run(daemon.run_once())
    assert _g("quant_datasource_probe_failures_total", source="cb_futu", error_type="circuit_open") == 1.0


def test_probe_exception_treated_unreachable(patched_record_probe):
    fetch_fn = mock.AsyncMock(side_effect=RuntimeError("connection refused"))
    daemon = DataSourceProbeDaemon(
        probes=[_ds_probe("ex_fred", action="MACRO_SERIES")],
        fetch_fn=fetch_fn,
        llm_health_fn=mock.AsyncMock(return_value={}),
    )
    results = asyncio.run(daemon.run_once())
    assert results["ex_fred"] is False
    assert _g("quant_datasource_probe_success", source="ex_fred") == 0.0
    assert _g("quant_datasource_probe_failures_total", source="ex_fred", error_type="network") == 1.0
