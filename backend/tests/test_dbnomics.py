"""
MACRO-04: DbnomicsService 单测（免费新兴市场 CPI 源）
=====================================================

覆盖 dbnomics.py:
- 序列 ID 构造
- Redis 缓存命中 / 未命中
- HTTP 成功解析 docs → events（含 period_start_day / 退化年份）
- 过滤未知国家 / null 观测 / 长度不一致
- 空 docs / HTTP 异常 → skipped
- _build_date 三种分支
"""

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.macro.dbnomics import (
    EM_COUNTRIES,
    DbnomicsService,
    dbnomics_service,
)


@contextmanager
def _patched_redis(get_value=None):
    r = AsyncMock()
    r.get.return_value = get_value
    r.set.return_value = True
    with patch("backend.services.macro.dbnomics.redis_client", r):
        yield r


def _client_with_get(payload):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    client.get = AsyncMock(return_value=resp)
    return client


def _doc(ref_area, periods, values, start_days=None):
    doc = {"dimensions": {"REF_AREA": ref_area}, "period": periods, "value": values}
    if start_days is not None:
        doc["period_start_day"] = start_days
    return doc


@pytest.mark.asyncio
async def test_series_ids_cover_em_countries():
    svc = DbnomicsService()
    ids = svc._series_ids()
    assert len(ids) == len(EM_COUNTRIES)
    for code in EM_COUNTRIES:
        assert any(code in i for i in ids)


@pytest.mark.asyncio
async def test_cache_hit_returns_redis_data():
    cached = [{"time": "2024-12-31 00:00:00", "country": "India", "event": "India CPI (YoY)"}]
    with _patched_redis(get_value=json.dumps(cached)):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "success"
    assert res["source"] == "redis_cache"
    assert res["data"] == cached


@pytest.mark.asyncio
async def test_parses_docs_with_period_start_day():
    payload = {"series": {"docs": [_doc("IND", ["2023", "2024"], [5.0, 6.1], ["2023-01-01", "2024-01-01"])]}}
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "success"
    assert res["source"] == "dbnomics"
    ev = res["data"][0]
    assert ev["country"] == "India"
    assert ev["actual"] == "6.1"
    assert ev["previous"] == "5.0"
    assert ev["time"] == "2024-01-01 00:00:00"


@pytest.mark.asyncio
async def test_parses_docs_year_fallback():
    payload = {"series": {"docs": [_doc("BRA", ["2024"], [4.5])]}}
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    ev = res["data"][0]
    assert ev["country"] == "Brazil"
    assert ev["actual"] == "4.5"
    assert ev["time"] == "2024-12-31 00:00:00"


@pytest.mark.asyncio
async def test_unknown_country_falls_back_to_code():
    # EM_COUNTRIES.get(code, code) 对未知国码回退为原 code（仍为 truthy），因此不会跳过
    payload = {"series": {"docs": [_doc("USA", ["2024"], [2.0])]}}
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "success"
    assert res["data"][0]["country"] == "USA"


@pytest.mark.asyncio
async def test_filters_null_observations():
    payload = {"series": {"docs": [_doc("MEX", ["2023", "2024"], [None, 4.5])]}}
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    ev = res["data"][0]
    assert ev["actual"] == "4.5"
    assert ev["previous"] == ""  # 仅剩一个有效观测


@pytest.mark.asyncio
async def test_mismatched_period_value_length_skipped():
    payload = {"series": {"docs": [_doc("IND", ["2023", "2024"], [5.0])]}}  # 长度不一致
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "skipped"


@pytest.mark.asyncio
async def test_empty_docs_returns_skipped():
    client = _client_with_get({"series": {"docs": []}})
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "skipped"


@pytest.mark.asyncio
async def test_http_error_returns_skipped():
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.get = AsyncMock(side_effect=Exception("boom"))
    with (
        _patched_redis(get_value=None),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar()
    assert res["status"] == "skipped"
    assert "失败" in res["message"]


@pytest.mark.asyncio
async def test_skip_cache_bypasses_redis():
    payload = {"series": {"docs": [_doc("CHN", ["2024"], [1.5])]}}
    client = _client_with_get(payload)
    with (
        _patched_redis(get_value=json.dumps([{"x": 1}])),
        patch("backend.services.macro.dbnomics.httpx.AsyncClient", return_value=client),
    ):
        svc = DbnomicsService()
        res = await svc.get_economic_calendar(skip_cache=True)
    assert res["source"] == "dbnomics"  # 未走缓存


def test_build_date_with_period_start_day():
    doc = {"period_start_day": ["2024-01-01", "2025-01-01"], "period": ["2024", "2025"]}
    assert DbnomicsService._build_date("2025", doc) == "2025-01-01 00:00:00"


def test_build_date_year_fallback():
    assert DbnomicsService._build_date("2024", {}) == "2024-12-31 00:00:00"


def test_build_date_invalid_year_fallback():
    assert DbnomicsService._build_date("ABC", {}) == "ABC-12-31 00:00:00"


def test_singleton_exists():
    assert isinstance(dbnomics_service, DbnomicsService)
