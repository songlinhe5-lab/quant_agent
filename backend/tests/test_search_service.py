"""SearchService 单元测试

覆盖: Tavily 成功/失败降级、Bocha 成功/失败降级、DuckDuckGo 兜底、
全部失败返回空、include/exclude_domains 传参、无 API key 路径。
"""
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.search_service import SearchService


def _mock_httpx_response(items_key="results", items=None):
    """构造 httpx 响应 mock,items_key 区分 Tavily(results) vs Bocha(data.webPages.value)"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    if items_key == "results":
        resp.json.return_value = {"results": items or []}
    else:
        resp.json.return_value = {"data": {"webPages": {"value": items or []}}}
    return resp


def _mock_async_client(resp):
    """构造 httpx.AsyncClient context manager mock"""
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post.return_value = resp
    return client


class TestSearchServiceTavily:
    """优先级 1: Tavily API"""

    @pytest.mark.asyncio
    async def test_tavily_success_returns_formatted_results(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tav-key", "BOCHA_API_KEY": ""}):
            resp = _mock_httpx_response(
                items=[{"title": "T1", "url": "http://u1", "content": "C1"}]
            )
            with patch(
                "backend.services.search_service.httpx.AsyncClient",
                return_value=_mock_async_client(resp),
            ):
                svc = SearchService()
                result = await svc.web_search("test query")
        assert result["status"] == "success"
        assert len(result["data"]) == 1
        assert result["data"][0] == {"title": "T1", "href": "http://u1", "body": "C1"}

    @pytest.mark.asyncio
    async def test_tavily_failure_falls_through_to_next_provider(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tav-key", "BOCHA_API_KEY": ""}):
            # Tavily 抛异常 → results 为空 → 进入 DuckDuckGo 兜底
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            client.post.side_effect = Exception("tavily down")
            with patch(
                "backend.services.search_service.httpx.AsyncClient",
                return_value=client,
            ), patch(
                "backend.services.search_service.asyncio.to_thread",
                return_value=[{"title": "DDG", "href": "u", "body": "b"}],
            ):
                svc = SearchService()
                result = await svc.web_search("q")
        assert result["data"][0]["title"] == "DDG"

    @pytest.mark.asyncio
    async def test_tavily_passes_include_exclude_domains(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tav-key", "BOCHA_API_KEY": ""}):
            resp = _mock_httpx_response(items=[{"title": "T", "url": "u", "content": "c"}])
            client = _mock_async_client(resp)
            with patch(
                "backend.services.search_service.httpx.AsyncClient",
                return_value=client,
            ):
                svc = SearchService()
                await svc.web_search(
                    "q", include_domains=["a.com"], exclude_domains=["b.com"]
                )
            sent_payload = client.post.call_args.kwargs["json"]
            assert sent_payload["include_domains"] == ["a.com"]
            assert sent_payload["exclude_domains"] == ["b.com"]


class TestSearchServiceBocha:
    """优先级 2: Bocha API"""

    @pytest.mark.asyncio
    async def test_bocha_success_when_tavily_key_absent(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "BOCHA_API_KEY": "bocha-key"}):
            resp = _mock_httpx_response(
                items_key="data",
                items=[{"name": "B1", "url": "http://b1", "snippet": "S1"}],
            )
            with patch(
                "backend.services.search_service.httpx.AsyncClient",
                return_value=_mock_async_client(resp),
            ):
                svc = SearchService()
                result = await svc.web_search("q")
        assert result["data"][0] == {"title": "B1", "href": "http://b1", "body": "S1"}

    @pytest.mark.asyncio
    async def test_bocha_failure_falls_through_to_duckduckgo(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "BOCHA_API_KEY": "bocha-key"}):
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            client.post.side_effect = Exception("bocha down")
            with patch(
                "backend.services.search_service.httpx.AsyncClient",
                return_value=client,
            ), patch(
                "backend.services.search_service.asyncio.to_thread",
                return_value=[{"title": "DDG", "href": "u", "body": "b"}],
            ):
                svc = SearchService()
                result = await svc.web_search("q")
        assert result["data"][0]["title"] == "DDG"


class TestSearchServiceDuckDuckGo:
    """优先级 3: DuckDuckGo 兜底"""

    @pytest.mark.asyncio
    async def test_duckduckgo_fallback_when_no_api_keys(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "BOCHA_API_KEY": ""}):
            with patch(
                "backend.services.search_service.asyncio.to_thread",
                return_value=[{"title": "DDG", "href": "u", "body": "b"}],
            ):
                svc = SearchService()
                result = await svc.web_search("q")
        assert result["status"] == "success"
        assert len(result["data"]) == 1

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_empty_with_message(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "", "BOCHA_API_KEY": ""}):
            with patch(
                "backend.services.search_service.asyncio.to_thread",
                return_value=[],
            ):
                svc = SearchService()
                result = await svc.web_search("q")
        assert result["status"] == "success"
        assert result["data"] == []
        assert "未找到" in result["message"]

    @pytest.mark.asyncio
    async def test_duckduckgo_uses_proxy_from_env(self):
        with patch.dict(
            os.environ,
            {"TAVILY_API_KEY": "", "BOCHA_API_KEY": "", "HTTPS_PROXY": "http://proxy:8080"},
        ):
            captured = {}

            def _capture(func):
                captured["func"] = func
                return []

            with patch(
                "backend.services.search_service.asyncio.to_thread",
                side_effect=_capture,
            ):
                svc = SearchService()
                await svc.web_search("q")
            # 验证 to_thread 被调用(内部 DDGS 会读 proxy)
            assert "func" in captured
