"""Search worker 单元测试 (handle_search 路由 + 聚合降级 _web_search_aggregated)。

底层 tavily/bocha/jina service 经 mock 替换, 不触真实外部 API。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from data_subservice import search_worker


@pytest.fixture
def mock_services(monkeypatch):
    tavily = MagicMock()
    tavily.search = AsyncMock(return_value={"status": "success", "data": [{"t": 1}]})
    bocha = MagicMock()
    bocha.search = AsyncMock(return_value={"status": "success", "data": [{"t": 2}]})
    jina = MagicMock()
    jina.scrape = AsyncMock(return_value={"status": "success", "data": {"content": "x"}})
    # 注意: search_worker 以 `from ... import tavily_service` 名称导入,
    # 必须替换 search_worker 模块命名空间内的引用, 而非 search_mod 的属性。
    monkeypatch.setattr(search_worker, "tavily_service", tavily)
    monkeypatch.setattr(search_worker, "bocha_service", bocha)
    monkeypatch.setattr(search_worker, "jina_service", jina)
    return {"tavily": tavily, "bocha": bocha, "jina": jina}


class TestHandleSearch:
    @pytest.mark.asyncio
    async def test_unknown_action(self, mock_services):
        out = await search_worker.handle_search("tavily", "BOGUS", {})
        assert "unknown" in out["error"]

    @pytest.mark.asyncio
    async def test_tavily(self, mock_services):
        out = await search_worker.handle_search("tavily", "SEARCH", {"query": "q"})
        assert out["data"][0]["t"] == 1

    @pytest.mark.asyncio
    async def test_tavily_web_search_alias(self, mock_services):
        out = await search_worker.handle_search("tavily", "WEB_SEARCH", {"query": "q"})
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_bocha(self, mock_services):
        out = await search_worker.handle_search("bocha", "SEARCH", {"query": "q"})
        assert out["data"][0]["t"] == 2

    @pytest.mark.asyncio
    async def test_jina(self, mock_services):
        out = await search_worker.handle_search("jina", "SEARCH", {"url": "https://x.com"})
        assert out["status"] == "success"

    @pytest.mark.asyncio
    async def test_unknown_source(self, mock_services):
        out = await search_worker.handle_search("duckduckgo", "SEARCH", {})
        assert "unknown search source" in out["error"]


class TestAggregated:
    @pytest.mark.asyncio
    async def test_tavily_success(self, mock_services):
        out = await search_worker._web_search_aggregated({"query": "q"})
        assert out["data"][0]["t"] == 1

    @pytest.mark.asyncio
    async def test_tavily_empty_falls_to_bocha(self, mock_services):
        mock_services["tavily"].search = AsyncMock(return_value={"status": "success", "data": []})
        out = await search_worker._web_search_aggregated({"query": "q"})
        assert out["data"][0]["t"] == 2

    @pytest.mark.asyncio
    async def test_tavily_exception_falls_to_bocha(self, mock_services):
        mock_services["tavily"].search = AsyncMock(side_effect=RuntimeError("boom"))
        out = await search_worker._web_search_aggregated({"query": "q"})
        assert out["data"][0]["t"] == 2

    @pytest.mark.asyncio
    async def test_all_empty(self, mock_services):
        mock_services["tavily"].search = AsyncMock(return_value={"status": "success", "data": []})
        mock_services["bocha"].search = AsyncMock(return_value={"status": "success", "data": []})
        out = await search_worker._web_search_aggregated({"query": "q"})
        assert out["data"] == []
