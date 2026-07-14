"""OBS-03: Web Vitals Prometheus 指标 + 心跳观察。"""

from __future__ import annotations

from prometheus_client import REGISTRY

from backend.routers.client import _observe_web_vitals
from backend.schemas.domain import ClientHeartbeatModel


class TestClientWebVitalMetrics:
    def test_web_vital_metrics_registered(self):
        names = {metric.name for metric in REGISTRY.collect()}
        assert "quant_client_web_vital_lcp_seconds" in names
        assert "quant_client_web_vital_cls" in names
        assert "quant_client_web_vital_inp_seconds" in names
        assert "quant_client_web_vital_ttfb_seconds" in names

    def test_observe_web_vitals_skips_none(self):
        payload = ClientHeartbeatModel(
            platform="web",
            appVersion="1.0",
            deviceId="d",
            timestamp=1,
        )
        _observe_web_vitals("web", payload)

    def test_observe_web_vitals_accepts_values(self):
        payload = ClientHeartbeatModel(
            platform="web",
            appVersion="1.0",
            deviceId="d",
            lcpMs=1000,
            cls=0.1,
            inpMs=200,
            ttfbMs=50,
            timestamp=1,
        )
        _observe_web_vitals("web", payload)
