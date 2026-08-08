"""
BE-ARCH-06f: 宏观日历统一经 Facade 聚合（fred / dbnomics / rbi）。

验证：
- get_economic_calendar 只经 datasource_registry.fetch 取数
- 多源 events 经 _merge 的 ECONOMIC_CALENDAR 分支做 actual 互补合并 + 去重
- 全源失败返回 ALL_SOURCES_FAILED
- MacroDataService 域方法正确透传
"""

from __future__ import annotations

import pytest

from backend.services.datasource import (
    Result,
    ResultStatus,
    datasource_registry,
    rate_limit_registry,
)
from backend.services.datasource.business.facade import DataServiceFacade, _merge_calendar_events
from backend.services.datasource.business.macro import MacroDataService


class _FakeSource:
    """最小 DataSourceInterface 替身，用于驱动 Facade 调度。"""

    def __init__(self, name: str, caps: list[str], data: dict, available: bool = True):
        self._name = name
        self._caps = caps
        self._data = data
        self._available = available

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> list[str]:
        return self._caps

    def is_available(self) -> bool:
        return self._available

    async def fetch(self, action: str, params: dict) -> Result:
        return Result.make_success(self._data, source=self._name, latency_ms=10.0)


@pytest.fixture(autouse=True)
def _clean():
    datasource_registry.clear()
    rate_limit_registry.clear()
    yield
    datasource_registry.clear()
    rate_limit_registry.clear()


def _register(name: str, caps: list[str], data: dict, available: bool = True) -> None:
    datasource_registry.register(_FakeSource(name, caps, data, available), instance_id="default")


# fred 给前瞻日历（多数无 actual），dbnomics/rbi 给新兴市场 CPI actual 兜底
_FRED_EVENTS = {
    "status": "success",
    "data": {
        "events": [
            {"country": "US", "event": "CPI YoY", "time": "2026-08-12", "estimate": "3.1%", "actual": None},
            {"country": "US", "event": "FOMC Rate", "time": "2026-08-15", "estimate": "5.0%", "actual": None},
        ],
        "source": "fred",
    },
    "source": "fred",
}

_DBNOMICS_EVENTS = {
    "status": "success",
    "data": {
        "events": [
            # 与 fred 同 key，补 actual
            {"country": "US", "event": "CPI YoY", "time": "2026-08-12", "estimate": None, "actual": "3.2%"},
            {"country": "CN", "event": "CPI YoY", "time": "2026-08-09", "estimate": None, "actual": "0.5%"},
        ],
        "source": "dbnomics",
    },
    "source": "dbnomics",
}

_RBI_EVENTS = {
    "status": "success",
    "data": {
        "events": [
            {"country": "IN", "event": "CPI YoY", "time": "2026-08-10", "estimate": None, "actual": "4.8%"},
        ],
        "source": "rbi",
    },
    "source": "rbi",
}


class TestEconomicCalendarFacade:
    @pytest.mark.asyncio
    async def test_single_source_returns_events(self):
        _register("fred", ["ECONOMIC_CALENDAR"], _FRED_EVENTS["data"])
        facade = DataServiceFacade()
        res = await facade.get_economic_calendar(days_ahead=7)
        assert res.is_success
        assert res.source == "fred"
        assert len(res.data["events"]) == 2

    @pytest.mark.asyncio
    async def test_multi_source_merges_actual_backfill(self):
        _register("fred", ["ECONOMIC_CALENDAR"], _FRED_EVENTS["data"])
        _register("dbnomics", ["ECONOMIC_CALENDAR"], _DBNOMICS_EVENTS["data"])
        _register("rbi", ["ECONOMIC_CALENDAR"], _RBI_EVENTS["data"])
        facade = DataServiceFacade()
        res = await facade.get_economic_calendar(days_ahead=7)
        assert res.is_success
        events = res.data["events"]
        # US CPI YoY: fred(无actual) + dbnomics(actual=3.2%) → 合并后应有 actual
        us_cpi = [e for e in events if e["country"] == "US" and e["event"] == "CPI YoY"]
        assert len(us_cpi) == 1
        assert us_cpi[0]["actual"] == "3.2%"
        assert us_cpi[0]["estimate"] == "3.1%"  # 来自 fred
        # 三源去重后共 4 条（US CPI 合并、US FOMC、CN CPI、IN CPI）
        assert len(events) == 4
        assert sorted(res.data.get("merged_sources", [])) == ["dbnomics", "fred", "rbi"]

    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_error(self):
        _register("fred", ["ECONOMIC_CALENDAR"], _FRED_EVENTS["data"], available=False)
        _register("dbnomics", ["ECONOMIC_CALENDAR"], _DBNOMICS_EVENTS["data"], available=False)
        facade = DataServiceFacade()
        res = await facade.get_economic_calendar(days_ahead=7)
        assert res.status == ResultStatus.ERROR
        assert res.error and res.error.code == "ALL_SOURCES_FAILED"

    @pytest.mark.asyncio
    async def test_prefer_sources_respected(self):
        _register("fred", ["ECONOMIC_CALENDAR"], _FRED_EVENTS["data"])
        _register("dbnomics", ["ECONOMIC_CALENDAR"], _DBNOMICS_EVENTS["data"])
        facade = DataServiceFacade()
        candidates = facade._select_source("ECONOMIC_CALENDAR", prefer_sources=["dbnomics"])
        assert candidates[0] == "dbnomics"


class TestMergeHelper:
    def test_merge_actual_backfill(self):
        r1 = Result.make_success(_FRED_EVENTS["data"], source="fred", latency_ms=10.0)
        r2 = Result.make_success(_DBNOMICS_EVENTS["data"], source="dbnomics", latency_ms=10.0)
        merged = _merge_calendar_events([r1, r2])
        us = [e for e in merged if e["country"] == "US" and e["event"] == "CPI YoY"]
        assert len(us) == 1
        assert us[0]["actual"] == "3.2%"

    def test_merge_dedup_count(self):
        r1 = Result.make_success(_FRED_EVENTS["data"], source="fred", latency_ms=10.0)
        r2 = Result.make_success(_DBNOMICS_EVENTS["data"], source="dbnomics", latency_ms=10.0)
        r3 = Result.make_success(_RBI_EVENTS["data"], source="rbi", latency_ms=10.0)
        merged = _merge_calendar_events([r1, r2, r3])
        assert len(merged) == 4


class TestMacroDataServiceDomain:
    @pytest.mark.asyncio
    async def test_macro_service_exposes_calendar(self):
        _register("fred", ["ECONOMIC_CALENDAR"], _FRED_EVENTS["data"])
        svc = MacroDataService()
        res = await svc.get_economic_calendar(days_ahead=7)
        assert res.is_success
        assert len(res.data["events"]) == 2
