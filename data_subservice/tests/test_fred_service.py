"""FREDService 单元测试 (_extract_fred_error 纯函数 + 各 get_* 网络分支)。

httpx.AsyncClient 经 mock 替换, 不触真实 api.stlouisfed.org。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from data_subservice._internal import fred as fred_mod
from data_subservice._internal.fred import FREDService, _extract_fred_error


def _mock_client(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    client = AsyncMock()
    client.__aenter__.return_value.get = AsyncMock(return_value=resp)
    return client


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)


class TestExtractFredError:
    @pytest.mark.parametrize(
        "body,expected",
        [
            ({"error_message": "bad key"}, "bad key"),
            ({"error": "nope"}, "nope"),
            ({"errors": [{"message": "x"}]}, "x"),
            ({"errors": []}, None),
            ({"ok": 1}, None),
            ("not a dict", None),
            (None, None),
        ],
    )
    def test_cases(self, body, expected):
        assert _extract_fred_error(body) == expected


class TestUnconfigured:
    @pytest.mark.asyncio
    async def test_series(self):
        assert "未配置" in (await FREDService().get_series_observations("DGS10"))["message"]

    @pytest.mark.asyncio
    async def test_releases(self):
        assert "未配置" in (await FREDService().get_releases_dates())["message"]

    @pytest.mark.asyncio
    async def test_econ_calendar(self):
        assert "未配置" in (await FREDService().get_economic_calendar())["message"]


class TestSeriesObservations:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"observations": [1]})):
            out = await FREDService().get_series_observations("DGS10")
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await FREDService().get_series_observations("DGS10")
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_non_200(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(500)):
            out = await FREDService().get_series_observations("DGS10")
        assert "500" in out["message"]

    @pytest.mark.asyncio
    async def test_json_error(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("bad json")
        client.__aenter__.return_value.get = AsyncMock(return_value=resp)
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=client):
            out = await FREDService().get_series_observations("DGS10")
        assert "not JSON" in out["message"]

    @pytest.mark.asyncio
    async def test_api_error_body(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(
            fred_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"error_message": "invalid key"})
        ):
            out = await FREDService().get_series_observations("DGS10")
        assert out["error_category"] == "api_error"


class TestReleasesDates:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(200, {"releases": []})):
            out = await FREDService().get_releases_dates()
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_429(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(429)):
            out = await FREDService().get_releases_dates()
        assert out["error_category"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_other(self, monkeypatch):
        monkeypatch.setenv("FRED_API_KEY", "k")
        with patch.object(fred_mod.httpx, "AsyncClient", return_value=_mock_client(403)):
            out = await FREDService().get_releases_dates()
        assert "403" in out["message"]
