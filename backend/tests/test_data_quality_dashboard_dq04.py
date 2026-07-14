"""
DQ-04 · 数据质量看板埋点测试

覆盖：Prometheus Gauge 导出、注册表聚合、overview API 契约。
"""

from __future__ import annotations

import time

import prometheus_client
import pytest

from backend.services.data_quality_monitor import (
    DataQualityMonitor,
    get_quality_monitor,
    quality_overview,
)


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    """每个用例使用干净注册表，避免跨测污染。"""
    monkeypatch.setattr(
        "backend.services.data_quality_monitor._MONITORS",
        {},
    )


class TestPrometheusExport:
    def test_export_sets_gauges(self):
        mon = DataQualityMonitor("futu")
        now = time.time()
        mon.validate_quote(
            {
                "ticker": "US.AAPL",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100.5,
                "volume": 1e6,
                "timestamp": now,
            }
        )
        # 强制再导一次确保指标存在
        mon.export_to_prometheus(valid=True)
        text = prometheus_client.generate_latest().decode()
        assert "quant_data_quality_dirty_rate" in text
        assert 'source="futu"' in text
        assert "quant_data_quality_completeness_rate" in text
        assert "quant_data_quality_checks_total" in text

    def test_anomaly_increments_dirty_rate(self):
        mon = get_quality_monitor("yfinance")
        mon.validate_quote(
            {
                "ticker": "US.TSLA",
                "open": 0,
                "high": 0,
                "low": 0,
                "close": 0,
                "volume": 1,
                "timestamp": time.time(),
            }
        )
        m = mon.get_metrics()
        assert m.dirty_rate > 0
        assert m.price_anomaly_count >= 1
        text = prometheus_client.generate_latest().decode()
        assert 'source="yfinance"' in text


class TestQualityOverview:
    def test_overview_lists_sources(self):
        get_quality_monitor("futu").validate_quote(
            {
                "ticker": "US.AAPL",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "timestamp": time.time(),
            }
        )
        get_quality_monitor("finnhub").validate_quote(
            {
                "ticker": "US.MSFT",
                "open": 20,
                "high": 21,
                "low": 19,
                "close": 20,
                "volume": 200,
                "timestamp": time.time(),
            }
        )
        overview = quality_overview()
        assert overview["source_count"] == 2
        sources = {s["source"] for s in overview["sources"]}
        assert sources == {"futu", "finnhub"}
        assert "alert_dirty_rate_threshold" in overview


@pytest.mark.asyncio
async def test_system_data_quality_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import backend.routers.system as system_mod

    get_quality_monitor("futu").validate_quote(
        {
            "ticker": "US.AAPL",
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
            "timestamp": time.time(),
        }
    )

    app = FastAPI()
    app.include_router(system_mod.router, prefix="/api/v1")

    async def _fake_user():
        return "tester"

    app.dependency_overrides[system_mod.get_current_user] = _fake_user
    client = TestClient(app)
    r = client.get("/api/v1/system/data-quality")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["data"]["source_count"] >= 1
    assert "quant_data_quality_dirty_rate" in body["grafana"]["metrics"]
