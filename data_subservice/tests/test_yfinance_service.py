"""YFinanceService 单元测试 (纯逻辑: 路由/数据不可用判定/DF 转换/技术指标空分支)。

底层 fetch_* 经 monkeypatch 替换为本地假数据, 不触发真实 yfinance 网络。
"""

import pandas as pd
import pytest

from data_subservice._internal.yfinance import service as yf_svc

# ── _is_data_unavailable ──────────────────────────────────────────────────


class TestIsDataUnavailable:
    @pytest.mark.parametrize(
        "msg,expected",
        [
            ('Yahoo error = "No data"', True),
            ("No data found for ticker", True),
            ("Delisted security", True),
            ("Empty dataset returned", True),
            ("not found", True),
            ("Rate limit exceeded", False),
            ("Connection timeout", False),
            ("", False),
        ],
    )
    def test_variants(self, msg, expected):
        assert yf_svc.YFinanceService._is_data_unavailable(Exception(msg)) is expected


# ── _df_to_records ────────────────────────────────────────────────────────


class TestDfToRecords:
    def test_none(self):
        assert yf_svc.YFinanceService()._df_to_records(None) == []

    def test_empty(self):
        assert yf_svc.YFinanceService()._df_to_records(pd.DataFrame()) == []

    def test_normal(self):
        df = pd.DataFrame(
            [
                {"Date": "2026-01-01", "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000},
                {"Date": "2026-01-02", "Open": 10.5, "High": 12.0, "Low": 10.0, "Close": 11.5, "Volume": 2000},
            ]
        )
        recs = yf_svc.YFinanceService()._df_to_records(df)
        assert len(recs) == 2
        assert recs[0]["close"] == 10.5
        assert recs[1]["volume"] == 2000

    def test_multiindex_columns(self):
        arrays = [["Close", "Open"], ["AAPL", "AAPL"]]
        df = pd.DataFrame(
            [[11.0, 10.0]],
            columns=pd.MultiIndex.from_arrays(arrays),
            index=["2026-01-01"],
        )
        df.index.name = "Date"
        df = df.reset_index()
        recs = yf_svc.YFinanceService()._df_to_records(df)
        # 拍平后第一级为 Close/Open, 应可取数
        assert len(recs) == 1

    def test_nan_rows_skipped(self):
        df = pd.DataFrame(
            [
                {"Date": "2026-01-01", "Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000},
                {"Date": "bad", "Open": "x", "High": "x", "Low": "x", "Close": "x", "Volume": "x"},
            ]
        )
        recs = yf_svc.YFinanceService()._df_to_records(df)
        assert len(recs) == 1


# ── fetch_yf_data 路由表 ──────────────────────────────────────────────────


class TestFetchYfDataRouting:
    """路由测试：把真实的 async 实例方法替换为 async 假实现，避免触发网络。"""

    @pytest.fixture
    def svc(self, monkeypatch):
        s = yf_svc.YFinanceService()

        async def fake_quote(self, symbol, **k):
            return {"quote": symbol}

        async def fake_history(self, symbol, **k):
            return {"hist": symbol}

        async def fake_flow(self, symbol, **k):
            return {"flow": symbol}

        async def fake_financials(self, symbol, **k):
            return {"fin": symbol}

        async def fake_option_chain(self, symbol, **k):
            return {"oc": symbol}

        async def fake_search(self, query, **k):
            return [{"q": query}]

        async def fake_tech(self, symbol, **k):
            return {"ti": symbol}

        monkeypatch.setattr(yf_svc.YFinanceService, "get_quote", fake_quote)
        monkeypatch.setattr(yf_svc.YFinanceService, "get_history", fake_history)
        monkeypatch.setattr(yf_svc.YFinanceService, "get_fund_flow", fake_flow)
        monkeypatch.setattr(yf_svc.YFinanceService, "get_financials", fake_financials)
        monkeypatch.setattr(yf_svc.YFinanceService, "get_option_chain", fake_option_chain)
        monkeypatch.setattr(yf_svc.YFinanceService, "search", fake_search)
        monkeypatch.setattr(yf_svc.YFinanceService, "get_tech_indicators", fake_tech)
        return s

    @pytest.mark.asyncio
    async def test_route_quote(self, svc):
        assert await svc.fetch_yf_data("QUOTE", "AAPL") == {"quote": "AAPL"}

    @pytest.mark.asyncio
    async def test_route_history(self, svc):
        assert await svc.fetch_yf_data("history", "AAPL") == {"hist": "AAPL"}

    @pytest.mark.asyncio
    async def test_route_flow(self, svc):
        assert await svc.fetch_yf_data("FLOW", "AAPL") == {"flow": "AAPL"}

    @pytest.mark.asyncio
    async def test_route_financials(self, svc):
        assert await svc.fetch_yf_data("financials", "AAPL") == {"fin": "AAPL"}

    @pytest.mark.asyncio
    async def test_route_option_chain(self, svc):
        assert await svc.fetch_yf_data("option_chain", "AAPL") == {"oc": "AAPL"}

    @pytest.mark.asyncio
    async def test_route_search(self, svc):
        assert await svc.fetch_yf_data("search", "AAPL") == [{"q": "AAPL"}]

    @pytest.mark.asyncio
    async def test_route_technical(self, svc):
        assert await svc.fetch_yf_data("technical", "AAPL") == {"ti": "AAPL"}

    @pytest.mark.asyncio
    async def test_unknown_endpoint(self, svc):
        res = await svc.fetch_yf_data("bogus", "AAPL")
        assert res["error"] == "unknown endpoint: bogus"


# ── get_tech_indicators 空分支 ─────────────────────────────────────────────


class TestGetTechIndicatorsEmpty:
    @pytest.mark.asyncio
    async def test_empty_df(self, monkeypatch):
        monkeypatch.setattr(yf_svc, "fetch_history", lambda *a, **k: None)
        svc = yf_svc.YFinanceService()
        res = await svc.get_tech_indicators("AAPL")
        assert res["error"] == "no history data"
