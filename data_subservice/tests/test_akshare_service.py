"""
AKShareService 单元测试（fetch_ak_data 路由 + 各 get_* 方法成功/失败分支）。

circuit_breaker.call 被替换为「直接执行传入 fn」的 async 桩，
从而验证各 service 方法对下层 akshare 叶子函数结果的真实包装逻辑。
"""

import pandas as pd
import pytest

from data_subservice._internal.akshare import service as ak_svc
from data_subservice._internal.akshare import quote as qmod


@pytest.fixture
def svc(monkeypatch):
    async def _fake_call(self, key, fn):
        return fn()

    fake_cb = type("CB", (), {
        "call": _fake_call,
        "record_success": lambda *a, **k: None,
        "record_failure": lambda *a, **k: None,
    })()
    monkeypatch.setattr(ak_svc, "circuit_breaker", fake_cb)
    return ak_svc.AKShareService()


class TestFetchAkDataRouting:
    @pytest.mark.asyncio
    async def test_unknown_endpoint(self, svc):
        res = await svc.fetch_ak_data("bogus", "000001")
        assert res["error"] == "unknown endpoint: bogus"

    @pytest.mark.asyncio
    async def test_quote(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_spot_a_quote", lambda t: {"ticker": t, "close": 1.0})
        res = await svc.fetch_ak_data("quote", "000001", market="A")
        assert res["ticker"] == "000001"

    @pytest.mark.asyncio
    async def test_history(self, svc, monkeypatch):
        # _call 为同步闭包, 叶子函数必须是同步返回值(被 fake_call 直接 fn())
        def fake_history(*a, **k):
            return pd.DataFrame([{"close": 1.0}])

        monkeypatch.setattr(ak_svc, "get_history", fake_history)
        res = await svc.fetch_ak_data("history", "000001")
        assert res["source"] == "akshare"
        assert res["data"] == [{"close": 1.0}]

    @pytest.mark.asyncio
    async def test_flow(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_individual_flow", lambda s: {"flow": s})
        res = await svc.fetch_ak_data("flow", "000001")
        assert res == {"flow": "000001"}

    @pytest.mark.asyncio
    async def test_cal(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_economic_calendar", lambda **k: {"status": "success", "data": [], "source": "akshare_calendar"})
        res = await svc.fetch_ak_data("cal")
        assert res["status"] == "success"
        assert res["data"] == []

    @pytest.mark.asyncio
    async def test_news(self, svc, monkeypatch):
        def fake_news(**k):
            return [{"新闻标题": "h"}]

        monkeypatch.setattr(ak_svc, "get_hk_news", fake_news)
        res = await svc.fetch_ak_data("news")
        assert res == [{"新闻标题": "h"}]


class TestGetMethods:
    @pytest.mark.asyncio
    async def test_get_quote(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_spot_a_quote", lambda t: {"ticker": t, "close": 1.0})
        res = await svc.get_quote("000001")
        assert res["ticker"] == "000001"

    @pytest.mark.asyncio
    async def test_get_quote_no_data(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_spot_a_quote", lambda t: None)
        res = await svc.get_quote("000001")
        assert res["error"] == "no data"

    @pytest.mark.asyncio
    async def test_get_quote_exception(self, svc, monkeypatch):
        def boom(t):
            raise RuntimeError("rate limited")

        monkeypatch.setattr(ak_svc, "get_spot_a_quote", boom)
        res = await svc.get_quote("000001")
        assert "rate limited" in res["error"]

    @pytest.mark.asyncio
    async def test_get_history(self, svc, monkeypatch):
        def fake_history(*a, **k):
            return pd.DataFrame([{"close": 1.0}])

        monkeypatch.setattr(ak_svc, "get_history", fake_history)
        res = await svc.get_history("000001")
        assert res["source"] == "akshare"
        assert res["data"] == [{"close": 1.0}]

    @pytest.mark.asyncio
    async def test_get_fund_flow(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_individual_flow", lambda s: {"flow": s})
        res = await svc.get_fund_flow("000001")
        assert res == {"flow": "000001"}

    @pytest.mark.asyncio
    async def test_get_econ_cal(self, svc, monkeypatch):
        monkeypatch.setattr(ak_svc, "get_economic_calendar", lambda **k: {"status": "success", "data": [], "source": "akshare_calendar"})
        res = await svc.get_econ_cal()
        assert res["status"] == "success"
        assert res["data"] == []

    @pytest.mark.asyncio
    async def test_get_hk_news(self, svc, monkeypatch):
        def fake_news(**k):
            return [{"新闻标题": "h"}]

        monkeypatch.setattr(ak_svc, "get_hk_news", fake_news)
        res = await svc.get_hk_news()
        assert res == [{"新闻标题": "h"}]
