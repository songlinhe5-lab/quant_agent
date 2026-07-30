"""
MACRO: MacroCalendarAggregator 深度单测（补齐多源聚合/归一化/兜底分支）
====================================================================

覆盖 macro_calendar_service.py:
- aggregate 主链路: AKShare 主源 / EM 回填(dbnomics→rbi) / FRED 回填 / Finnhub 兜底 / FRED 兜底
- _safe 异常包裹
- _fetch_em 按优先级串联
- _extract / _normalize / _to_utc_iso 各时间格式与异常分支
- _merge / _completeness 去重补全
- _build_message 空/有贡献源
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import settings
from backend.services.macro.macro_calendar_service import MacroCalendarAggregator


def _fake_market_data(ak=None, dbnomics=None, rbi=None, finnhub=None, fred=None, backfill=None):
    md = MagicMock()
    md.get_economic_calendar_ak = AsyncMock(return_value=ak or {"status": "success", "data": []})
    md.get_economic_calendar_dbnomics = AsyncMock(return_value=dbnomics or {"status": "success", "data": []})
    md.get_economic_calendar_rbi = AsyncMock(return_value=rbi or {"status": "success", "data": []})
    md.get_economic_calendar_finnhub = AsyncMock(return_value=finnhub or {"status": "success", "data": []})
    md.get_economic_calendar_fred = AsyncMock(return_value=fred or {"status": "success", "data": []})
    md.backfill_fred_actuals = AsyncMock(side_effect=backfill if backfill is not None else (lambda merged: merged))
    return md


@pytest.fixture
def patched_settings(monkeypatch):
    monkeypatch.setattr(settings, "em_source_priority", "dbnomics,rbi")


class TestAggregateMain:
    async def test_akshare_primary(self, patched_settings):
        md = _fake_market_data(
            ak={
                "status": "success",
                "data": [{"time": "2024-01-01", "country": "US", "event": "CPI", "impact": "high"}],
            }
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert res["status"] == "success"
        assert len(res["data"]) >= 1
        assert "akshare" in res["sources_contributed"]

    async def test_em_fallback_when_ak_empty(self, patched_settings):
        md = _fake_market_data(
            dbnomics={
                "status": "success",
                "data": [{"time": "2024-01-01", "country": "India", "event": "CPI", "impact": "medium"}],
            }
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert any(e["_src"] == "dbnomics" for e in res["data"])

    async def test_finnhub_fallback_when_all_empty(self, patched_settings):
        md = _fake_market_data(
            finnhub={
                "status": "success",
                "data": [{"time": "2024-01-01", "country": "US", "event": "NFP", "impact": "high"}],
            }
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert any(e["_src"] == "finnhub" for e in res["data"])

    async def test_fred_fallback_last_resort(self, patched_settings):
        md = _fake_market_data(
            fred={
                "status": "success",
                "data": [{"time": "2024-01-01", "country": "US", "event": "PCE", "impact": "high"}],
            }
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert any(e["_src"] == "fred" for e in res["data"])

    async def test_warning_when_nothing(self, patched_settings):
        md = _fake_market_data()
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert res["status"] == "warning"
        assert "未返回数据" in res["message"]

    async def test_ak_raises_caught_by_safe(self, patched_settings):
        md = _fake_market_data()
        md.get_economic_calendar_ak = AsyncMock(side_effect=Exception("ak down"))
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert res["status"] == "warning"  # 全空

    async def test_backfill_fred_failure_caught(self, patched_settings):
        md = _fake_market_data(
            ak={"status": "success", "data": [{"time": "2024-01-01", "country": "US", "event": "CPI"}]},
            backfill=Exception("fred down"),
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc.aggregate()
        assert res["status"] == "success"  # 回填失败不影响主结果


class TestExtractNormalize:
    def test_extract_non_dict(self):
        svc = MacroCalendarAggregator()
        assert svc._extract(None, "akshare") == []

    def test_extract_no_data(self):
        svc = MacroCalendarAggregator()
        assert svc._extract({"status": "success"}, "akshare") == []

    def test_normalize_impact_default(self):
        svc = MacroCalendarAggregator()
        ev = svc._normalize({"time": "2024-01-01", "country": "US", "event": "CPI", "impact": "weird"}, "akshare")
        assert ev["impact"] == "low"

    def test_normalize_full(self):
        svc = MacroCalendarAggregator()
        ev = svc._normalize(
            {
                "time": "2024-01-01",
                "country": "US",
                "event": "CPI",
                "impact": "high",
                "previous": "1",
                "estimate": "2",
                "actual": "3",
            },
            "fred",
        )
        assert ev["_src"] == "fred"
        assert ev["actual"] == "3"


class TestToUtcIso:
    def test_t_format(self):
        svc = MacroCalendarAggregator()
        out = svc._to_utc_iso("2024-01-01T08:30:00", "UTC")
        assert out.endswith("Z")

    def test_space_format(self):
        svc = MacroCalendarAggregator()
        out = svc._to_utc_iso("2024-01-01 08:30:00", "UTC")
        assert out.endswith("Z")

    def test_minute_format(self):
        svc = MacroCalendarAggregator()
        out = svc._to_utc_iso("2024-01-01 08:30", "UTC")
        assert out.endswith("Z")

    def test_date_only(self):
        svc = MacroCalendarAggregator()
        out = svc._to_utc_iso("2024-01-01", "UTC")
        assert out.startswith("2024-01-01")

    def test_empty_returns_today(self):
        svc = MacroCalendarAggregator()
        assert svc._to_utc_iso("", "UTC") is not None

    def test_garbage_returns_raw(self):
        svc = MacroCalendarAggregator()
        assert svc._to_utc_iso("garbage", "UTC") == "garbageZ"

    def test_timezone_conversion(self):
        svc = MacroCalendarAggregator()
        out = svc._to_utc_iso("2024-01-01 08:30:00", "Asia/Shanghai")
        assert out.endswith("Z")


class TestMerge:
    def test_merge_keeps_more_complete(self):
        svc = MacroCalendarAggregator()
        events = [
            {"country": "US", "event": "CPI", "date": "2024-01-01", "actual": "", "estimate": "", "previous": ""},
            {
                "country": "US",
                "event": "CPI",
                "date": "2024-01-01",
                "actual": "3.0",
                "estimate": "2.9",
                "previous": "2.8",
            },
        ]
        merged = svc._merge(events)
        assert len(merged) == 1
        assert merged[0]["actual"] == "3.0"

    def test_completeness(self):
        assert MacroCalendarAggregator._completeness({"actual": "1", "estimate": "2", "previous": "3"}) == 3


class TestBuildMessage:
    def test_empty(self):
        svc = MacroCalendarAggregator()
        assert "未返回数据" in svc._build_message([])

    def test_contributed(self):
        svc = MacroCalendarAggregator()
        msg = svc._build_message(["akshare", "fred"])
        assert "AKShare" in msg and "FRED" in msg


class TestFetchEm:
    async def test_fetch_em_priority(self, patched_settings):
        md = _fake_market_data(
            dbnomics={"status": "success", "data": [{"time": "2024-01-01", "country": "India", "event": "CPI"}]},
            rbi={"status": "success", "data": []},
        )
        svc = MacroCalendarAggregator()
        with patch.object(MacroCalendarAggregator, "_market_data", return_value=md):
            res = await svc._fetch_em(7, 0, False)
        assert res["sources"] == ["dbnomics"]
        assert len(res["data"]) == 1
