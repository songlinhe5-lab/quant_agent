"""ApeWisdom 散户热度数据源单测（对齐 test_finnhub_api.py 模式）。

不依赖真实外网：用 monkeypatch 注入 _get 返回，覆盖正常/异常/分页/字段归一化。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from data_subservice._internal.sentiment.apewisdom import ApeWisdomService


def _fake_page(rank_start: int, count: int) -> dict:
    return {
        "status": "success",
        "data": {
            "data": [
                {
                    "rank": rank_start + i,
                    "ticker": f"SYM{i}",
                    "name": f"Company {i}",
                    "mentions": 100 + i,
                    "upvotes": 50 + i,
                    "rank_24h_ago": rank_start + i + 5,
                    "mentions_24h_ago": 80 + i,
                }
                for i in range(count)
            ]
        },
    }


@pytest.mark.asyncio
async def test_get_trending_single_page_success():
    svc = ApeWisdomService()
    with patch.object(svc, "_get", new=AsyncMock(return_value=_fake_page(1, 100))):
        r = await svc.get_trending(filter="all", page=1)
    assert r["status"] == "success"
    assert r["source"] == "apewisdom"
    assert len(r["data"]) == 100
    item = r["data"][0]
    assert item["ticker"] == "SYM0"
    assert item["mentions_delta_pct"] == pytest.approx((100 - 80) / 80, abs=1e-3)
    assert item["rank_24h_ago"] == 6


@pytest.mark.asyncio
async def test_get_trending_invalid_filter():
    svc = ApeWisdomService()
    r = await svc.get_trending(filter="not_a_filter", page=1)
    assert r["status"] == "error"
    assert "无效的 filter" in r["message"]


@pytest.mark.asyncio
async def test_get_trending_top_n_pagination():
    # top_n=150 → 需翻 2 页（每页 100），_get 按 page 返回对应页
    svc = ApeWisdomService()
    pages = {1: _fake_page(1, 100), 2: _fake_page(101, 60)}

    async def fake_get(path, params=None):
        # path 形如 /filter/all/page/1
        p = int(path.rstrip("/").split("/")[-1])
        return pages[p]

    with patch.object(svc, "_get", new=fake_get):
        r = await svc.get_trending(filter="all", page=1, top_n=150)
    assert r["status"] == "success"
    assert len(r["data"]) == 150
    # page1=SYM0..SYM99, page2=SYM0..SYM59; 截断 150 后最后一条是 page2 第 50 条 (SYM49)
    assert r["data"][-1]["ticker"] == "SYM49"


@pytest.mark.asyncio
async def test_get_trending_429_rate_limit():
    svc = ApeWisdomService()
    with patch.object(
        svc,
        "_get",
        new=AsyncMock(
            return_value={"status": "error", "message": "ApeWisdom 429 rate limited", "error_category": "rate_limit"}
        ),
    ):
        r = await svc.get_trending(filter="all", page=1)
    assert r["status"] == "error"
    assert r["error_category"] == "rate_limit"


@pytest.mark.asyncio
async def test_get_trending_mid_pagination_failure_returns_partial():
    svc = ApeWisdomService()

    async def fake_get(path, params=None):
        p = int(path.rstrip("/").split("/")[-1])
        if p == 1:
            return _fake_page(1, 100)
        return {"status": "error", "message": "boom", "error_category": "normal"}

    with patch.object(svc, "_get", new=fake_get):
        r = await svc.get_trending(filter="all", page=1, top_n=250)
    assert r["status"] == "error"
    assert len(r["collected"]) == 100  # 已收集部分不丢失
