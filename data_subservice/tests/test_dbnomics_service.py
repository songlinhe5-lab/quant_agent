"""DBnomics DbnomicsService 单元测试 — 覆盖两个方法 200/429/其他/异常分支 (mock httpx)。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import data_subservice._internal.dbnomics as dbn_mod
from data_subservice._internal.dbnomics import DbnomicsService


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _client(status=200, payload=None, raise_exc=None):
    """返回一个 AsyncClient 替身, .get() 返回 _Resp 或可抛异常。"""
    client = MagicMock()

    async def get(url, params=None):
        if raise_exc is not None:
            raise raise_exc
        return _Resp(status, payload)

    client.get = get
    # 支持 async with
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture
def svc():
    return DbnomicsService()


# ─── get_economic_calendar ──────────────────────────────────────────
class TestGetEconomicCalendar:
    async def test_success(self, svc):
        client = _client(200, {"datasets": [{"id": "X"}]})
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_economic_calendar()
        assert out["status"] == "success"
        assert out["data"] == {"datasets": [{"id": "X"}]}

    async def test_429(self, svc):
        client = _client(429)
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_economic_calendar()
        assert out["status"] == "error"
        assert out["error_category"] == "rate_limit"

    async def test_other_status(self, svc):
        client = _client(503)
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_economic_calendar()
        assert out["status"] == "error"
        assert "503" in out["message"]

    async def test_exception(self, svc):
        client = _client(raise_exc=RuntimeError("net down"))
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_economic_calendar()
        assert out["status"] == "error"
        assert "net down" in out["message"]


# ─── get_em_cpi_series ──────────────────────────────────────────────
class TestGetEmCpiSeries:
    async def test_default_codes(self, svc):
        client = _client(200, {"series": {"a": 1}})
        captured = {}
        orig = client.get

        async def spy(url, params=None):
            captured["url"] = url
            captured["params"] = params
            return await orig(url, params)

        client.get = spy
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_em_cpi_series()
        assert out["status"] == "success"
        # 默认 9 个 G20 新兴市场国码
        assert len(captured["params"]["series_ids"].split(",")) == 9

    async def test_custom_codes(self, svc):
        client = _client(200, {"series": {}})
        captured = {}
        orig = client.get

        async def spy(url, params=None):
            captured["params"] = params
            return await orig(url, params)

        client.get = spy
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_em_cpi_series(countries=["ARG", "BRA"])
        assert out["status"] == "success"
        ids = captured["params"]["series_ids"].split(",")
        assert ids == [
            "OECD/DSD_G20_PRICES@DF_G20_PRICES/ARG.A.N.CPI.PA._T.N.GY",
            "OECD/DSD_G20_PRICES@DF_G20_PRICES/BRA.A.N.CPI.PA._T.N.GY",
        ]

    async def test_429(self, svc):
        client = _client(429)
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_em_cpi_series()
        assert out["status"] == "error"
        assert out["error_category"] == "rate_limit"

    async def test_other_status(self, svc):
        client = _client(500)
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_em_cpi_series()
        assert out["status"] == "error"
        assert "500" in out["message"]

    async def test_exception(self, svc):
        client = _client(raise_exc=ConnectionError("boom"))
        with patch.object(dbn_mod.httpx, "AsyncClient", return_value=client):
            out = await svc.get_em_cpi_series()
        assert out["status"] == "error"
        assert "boom" in out["message"]
