"""SearchService 单元测试 (BE-ARCH-07d 合规: 仅远程代理)

覆盖: 经 data_source_router.fetch_search 远程调用, Tavily -> Bocha 降级、
全部远程源失败返回空、include/exclude_domains 透传、异常降级。
主服务不再直连任何外部搜索 API (api.tavily.com / api.bochaai.com / duckduckgo)。
"""

from unittest.mock import patch

import pytest

from backend.services.search.service import _SEARCH_SOURCE_PRIORITY, SearchService


def _fake_fetch(seq):
    """构造 fetch_search: 按 source 返回对应结果, 不在 seq 中的 source 返回 error。"""

    async def _f(source, **params):
        return seq.get(source, {"status": "error", "message": f"{source} unavailable"})

    return _f


class TestSearchServiceRemoteTavily:
    """优先级 1: 经远程 Tavily 代理"""

    @pytest.mark.asyncio
    async def test_tavily_success_returns_formatted_results(self):
        svc = SearchService()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_fake_fetch(
                {"tavily": {"status": "success", "data": [{"title": "T1", "href": "http://u1", "body": "C1"}]}}
            ),
        ):
            result = await svc.web_search("test query")
        assert result["status"] == "success"
        assert result["data"][0] == {"title": "T1", "href": "http://u1", "body": "C1"}

    @pytest.mark.asyncio
    async def test_tavily_failure_falls_through_to_bocha(self):
        svc = SearchService()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_fake_fetch(
                {"bocha": {"status": "success", "data": [{"title": "B1", "href": "http://b1", "body": "S1"}]}}
            ),
        ):
            result = await svc.web_search("q")
        assert result["data"][0] == {"title": "B1", "href": "http://b1", "body": "S1"}

    @pytest.mark.asyncio
    async def test_tavily_passes_include_exclude_domains(self):
        svc = SearchService()
        captured = {}

        async def _capture(source, **params):
            captured.update(params)
            return {"status": "success", "data": []}

        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_capture,
        ):
            await svc.web_search("q", include_domains=["a.com"], exclude_domains=["b.com"])
        assert captured["include_domains"] == ["a.com"]
        assert captured["exclude_domains"] == ["b.com"]


class TestSearchServiceRemoteBocha:
    """优先级 2: 经远程 Bocha 代理 (Tavily 不可用时)"""

    @pytest.mark.asyncio
    async def test_bocha_success_when_tavily_unavailable(self):
        svc = SearchService()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_fake_fetch(
                {"bocha": {"status": "success", "data": [{"title": "B1", "href": "http://b1", "body": "S1"}]}}
            ),
        ):
            result = await svc.web_search("q")
        assert result["data"][0] == {"title": "B1", "href": "http://b1", "body": "S1"}


class TestSearchServiceAllFail:
    """全部远程源失败/空: 返回空 data + message (不再直连 DuckDuckGo)"""

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_empty_with_message(self):
        svc = SearchService()
        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_fake_fetch({}),
        ):
            result = await svc.web_search("q")
        assert result["status"] == "success"
        assert result["data"] == []
        assert "未找到" in result["message"]

    @pytest.mark.asyncio
    async def test_remote_exception_falls_through_then_empty(self):
        svc = SearchService()
        calls = []

        async def _boom(source, **params):
            calls.append(source)
            raise RuntimeError("search node unreachable")

        with patch(
            "backend.services.datasource.router.data_source_router.fetch_search",
            new=_boom,
        ):
            result = await svc.web_search("q")
        # 两个源都被尝试过
        assert set(calls) == set(_SEARCH_SOURCE_PRIORITY)
        assert result["data"] == []
        assert "message" in result


class TestSearchServiceNoDirectExternalAPI:
    """07d 验收: 主服务搜索服务不直连任何外部搜索 API"""

    def test_no_external_domains_in_source(self):
        import inspect

        src = inspect.getsource(SearchService)
        assert "api.tavily.com" not in src
        assert "api.bochaai.com" not in src
        assert "duckduckgo_search" not in src
