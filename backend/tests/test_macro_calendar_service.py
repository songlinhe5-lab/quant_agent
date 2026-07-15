"""macro_calendar_service 聚合器 + 新兴市场双源 + FRED 回填 单元测试"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.macro_calendar_service import MacroCalendarAggregator
import backend.services.macro_calendar_service as mcs
from backend.services.dbnomics_service import dbnomics_service
from backend.services.fred_service import fred_service
from backend.services.finnhub_service import finnhub_service
from backend.services.rbi_service import rbi_service


def test_normalize_timezones():
    a = MacroCalendarAggregator()
    # 北京时间 08:30 -> UTC 00:30
    cn = a._normalize(
        {"time": "2024-05-15 08:30:00", "country": "CN", "event": "CPI", "impact": "high",
         "previous": "", "estimate": "", "actual": ""}, "akshare")
    assert cn["date"] == "2024-05-15T00:30:00Z"
    # UTC 不变
    us = a._normalize(
        {"time": "2024-05-15 12:30:00", "country": "US", "event": "CPI", "impact": "medium",
         "previous": "", "estimate": "", "actual": ""}, "finnhub")
    assert us["date"] == "2024-05-15T12:30:00Z"
    # 美东 08:30 -> UTC 12:30
    fred = a._normalize(
        {"time": "2024-05-15 08:30:00", "country": "US", "event": "CPI", "impact": "high",
         "previous": "", "estimate": "", "actual": ""}, "fred")
    assert fred["date"] == "2024-05-15T12:30:00Z"


def test_merge_prefers_complete():
    a = MacroCalendarAggregator()
    events = [
        {"date": "2024-05-15T00:00:00Z", "country": "US", "event": "CPI", "impact": "high",
         "previous": "", "estimate": "", "actual": "", "_src": "fred"},
        {"date": "2024-05-15T00:00:00Z", "country": "US", "event": "CPI", "impact": "high",
         "previous": "2.0", "estimate": "2.1", "actual": "2.3", "_src": "akshare"},
    ]
    merged = a._merge(events)
    assert len(merged) == 1
    assert merged[0]["actual"] == "2.3"
    assert merged[0]["_src"] == "akshare"


def test_aggregate_merges_sources():
    """主源 AKShare 有数据时, Finnhub 仅作兜底不应被调用。"""
    a = MacroCalendarAggregator()
    with patch.object(
        mcs.market_data, "get_economic_calendar_ak",
        new=AsyncMock(return_value={"status": "success", "data": [
            {"time": "2024-06-01 08:30:00", "country": "CN", "event": "CPI", "impact": "high",
             "previous": "", "estimate": "", "actual": ""}]}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_dbnomics",
        new=AsyncMock(return_value={"status": "skipped", "data": []}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_rbi",
        new=AsyncMock(return_value={"status": "skipped", "data": []}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_finnhub",
        new=AsyncMock(return_value={"status": "success", "data": [
            {"time": "2024-06-01 12:30:00", "country": "US", "event": "CPI", "impact": "medium",
             "previous": "", "estimate": "", "actual": ""}]}),
    ) as m_fh, patch.object(
        mcs.market_data, "backfill_fred_actuals",
        new=AsyncMock(side_effect=lambda e, *args, **kwargs: e),
    ):
        res = asyncio.run(a.aggregate(days_ahead=7))
    assert res["status"] == "success"
    # AKShare 返回 1 条, Finnhub 兜底不应被触发 (merged 非空)
    assert len(res["data"]) == 1
    assert res["sources_contributed"] == ["akshare"]
    m_fh.assert_not_called()
    assert "回填" in res["message"]


def test_aggregate_finnhub_fallback_when_empty():
    """主源 AKShare 全空时, Finnhub 作为兜底前瞻日历被调用。"""
    a = MacroCalendarAggregator()
    with patch.object(
        mcs.market_data, "get_economic_calendar_ak",
        new=AsyncMock(return_value={"status": "success", "data": []}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_dbnomics",
        new=AsyncMock(return_value={"status": "skipped", "data": []}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_rbi",
        new=AsyncMock(return_value={"status": "skipped", "data": []}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_finnhub",
        new=AsyncMock(return_value={"status": "success", "data": [
            {"time": "2024-06-01 12:30:00", "country": "US", "event": "CPI", "impact": "medium",
             "previous": "", "estimate": "", "actual": ""}]}),
    ), patch.object(
        mcs.market_data, "get_economic_calendar_fred",
        new=AsyncMock(return_value={"status": "skipped", "data": []}),
    ), patch.object(
        mcs.market_data, "backfill_fred_actuals",
        new=AsyncMock(side_effect=lambda e, *args, **kwargs: e),
    ):
        res = asyncio.run(a.aggregate(days_ahead=7))
    assert res["status"] == "success"
    assert len(res["data"]) == 1
    assert res["sources_contributed"] == ["finnhub"]


def test_fred_backfill_fills_actual():
    events = [{"time": "2024-06-12 08:30:00", "country": "US", "event": "CPI", "impact": "high",
               "previous": "", "estimate": "", "actual": ""}]
    series = {"status": "success", "data": [
        {"date": "2024-05-01", "value": 3.3}, {"date": "2024-06-01", "value": 3.4}]}
    with patch.object(fred_service, "get_series_observations", new=AsyncMock(return_value=series)):
        out = asyncio.run(fred_service.backfill_actuals(events))
    assert out[0]["actual"] == "3.4"


def test_fred_backfill_skips_when_actual_present():
    events = [{"time": "2024-06-12 08:30:00", "country": "US", "event": "CPI", "impact": "high",
               "previous": "", "estimate": "", "actual": "3.4"}]
    with patch.object(fred_service, "get_series_observations", new=AsyncMock(return_value={"status": "success", "data": []})) as m:
        out = asyncio.run(fred_service.backfill_actuals(events))
    assert out[0]["actual"] == "3.4"
    m.assert_not_called()


def test_finnhub_skips_without_key():
    old = finnhub_service._get_api_key
    finnhub_service._get_api_key = lambda: ""
    try:
        res = asyncio.run(finnhub_service.get_economic_calendar())
    finally:
        finnhub_service._get_api_key = old
    assert res["status"] == "skipped"


def test_dbnomics_parses_g20_cpi():
    """DBnomics 返回 G20 CPI 年度同比, 解析出印度/巴西等新兴市场 actual 事件。"""
    payload = {
        "series": {
            "docs": [
                {
                    "dimensions": {"REF_AREA": "IND"},
                    "period": ["2023", "2024", "2025"],
                    "period_start_day": ["2023-01-01", "2024-01-01", "2025-01-01"],
                    "value": [5.5, 5.4, 4.9],
                },
                {
                    "dimensions": {"REF_AREA": "BRA"},
                    "period": ["2023", "2024", "2025"],
                    "period_start_day": ["2023-01-01", "2024-01-01", "2025-01-01"],
                    "value": [4.6, 4.4, 5.0],
                },
            ]
        }
    }
    with patch("backend.services.dbnomics_service.redis_client") as m_redis, \
         patch("backend.services.dbnomics_service.httpx.AsyncClient") as m_client:
        m_redis.get.return_value = None
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        m_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
        res = asyncio.run(dbnomics_service.get_economic_calendar())
    assert res["status"] == "success"
    ev_by_country = {e["country"]: e for e in res["data"]}
    assert "India" in ev_by_country and "Brazil" in ev_by_country
    assert ev_by_country["India"]["actual"] == "4.9"
    assert ev_by_country["India"]["previous"] == "5.4"
    assert ev_by_country["India"]["event"] == "India CPI (YoY)"


def test_rbi_parses_worldbank():
    payload = [{"page": 1}, [{"date": "2023", "value": 5.5}, {"date": "2022", "value": 6.7}]]
    with patch("backend.services.rbi_service.redis_client") as m_redis, \
         patch("backend.services.rbi_service.httpx.AsyncClient") as m_client:
        m_redis.get.return_value = None
        resp = MagicMock()
        resp.json.return_value = payload
        resp.raise_for_status.return_value = None
        m_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
        res = asyncio.run(rbi_service.get_economic_calendar())
    assert res["status"] == "success"
    ev = res["data"][0]
    assert ev["country"] == "India"
    assert ev["event"] == "India CPI (YoY)"
    assert ev["actual"] == "5.5"


def test_finnhub_parse_calendar():
    raw = {"economicCalendar": [{"event": "CPI", "country": "US", "impact": "3",
                                 "prev": "0.2%", "consensus": "0.3%", "actual": "0.4%",
                                 "date": "2024-05-15 12:30:00"}]}
    with patch("backend.services.finnhub_service.redis_client") as m_redis, \
         patch("backend.services.finnhub_service.httpx.AsyncClient") as m_client:
        m_redis.get.return_value = None
        resp = MagicMock()
        resp.json.return_value = raw
        resp.raise_for_status.return_value = None
        m_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
        res = asyncio.run(finnhub_service.get_economic_calendar())
    assert res["status"] == "success"
    ev = res["data"][0]
    assert ev["country"] == "US"
    assert ev["impact"] == "high"
    assert ev["actual"] == "0.4%"
    assert ev["estimate"] == "0.3%"
