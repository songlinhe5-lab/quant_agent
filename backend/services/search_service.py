import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.core.middleware import httpx_log_request, httpx_log_response


class SearchService:
    """
    统一网页搜索服务
    按优先级降级调度：Tavily API -> Bocha API -> DuckDuckGo 免费爬虫
    """

    async def web_search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:  # noqa: E501
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        bocha_api_key = os.getenv("BOCHA_API_KEY")

        results = []

        # 💡 优先级 1：Tavily Search API (专为大模型 RAG 设计，免清洗，极简稳定)
        if tavily_api_key and not results:
            try:
                url = "https://api.tavily.com/search"
                payload = {
                    "api_key": tavily_api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                }  # noqa: E501
                if include_domains:
                    payload["include_domains"] = include_domains  # noqa: E701
                if exclude_domains:
                    payload["exclude_domains"] = exclude_domains  # noqa: E701

                async with httpx.AsyncClient(
                    timeout=30.0,
                    event_hooks={
                        "request": [httpx_log_request],
                        "response": [httpx_log_response],
                    },
                ) as client:  # noqa: E501
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                    for item in resp.json().get("results", []):
                        results.append(
                            {
                                "title": item.get("title"),
                                "href": item.get("url"),
                                "body": item.get("content"),
                            }
                        )  # noqa: E501
            except Exception as e:
                print(f"⚠️ [SearchService] Tavily 搜索失败，尝试降级: {repr(e)}")

        # 💡 优先级 2：博查 Bocha API (国内大模型 RAG 专属搜索，聚合百度/微信/搜狗，中文效果极佳)  # noqa: E501
        if bocha_api_key and not results:
            try:
                url = "https://api.bochaai.com/v1/web-search"
                headers = {
                    "Authorization": f"Bearer {bocha_api_key}",
                    "Content-Type": "application/json",
                }  # noqa: E501
                payload = {"query": query, "count": max_results}

                async with httpx.AsyncClient(
                    timeout=10.0,
                    event_hooks={
                        "request": [httpx_log_request],
                        "response": [httpx_log_response],
                    },
                ) as client:  # noqa: E501
                    resp = await client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    for item in resp.json().get("data", {}).get("webPages", {}).get("value", []):  # noqa: E501
                        results.append(
                            {
                                "title": item.get("name"),
                                "href": item.get("url"),
                                "body": item.get("snippet"),
                            }
                        )  # noqa: E501
            except Exception as e:
                print(f"⚠️ [SearchService] 博查 API 搜索失败，尝试降级: {repr(e)}")

        # 💡 优先级 3：终极兜底使用免费的 DuckDuckGo (开源网页爬虫)
        if not results:

            @retry(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
            )  # noqa: E501
            def _do_duckduckgo_search():
                # 修复导入警告：直接从官方库导入，并用 type: ignore 压制本地依赖缺失报红
                from duckduckgo_search import DDGS  # type: ignore

                proxy = (
                    os.getenv("HTTPS_PROXY")
                    or os.getenv("https_proxy")
                    or os.getenv("HTTP_PROXY")
                    or os.getenv("http_proxy")
                )  # noqa: E501
                with DDGS(proxy=proxy, timeout=20) as ddgs:
                    res = list(ddgs.text(query, max_results=max_results, region="cn-zh"))  # noqa: E501
                    if res:
                        return res  # noqa: E701
                    raise ValueError("DuckDuckGo 返回空数据")

            try:
                results = await asyncio.to_thread(_do_duckduckgo_search)
            except Exception as e:
                # 💡 提取可读的错误信息，而非抛出 RetryError 包装对象
                err_str = str(e)
                if "ValueError" in err_str and "DuckDuckGo" in err_str:
                    err_msg = "DuckDuckGo 返回空数据（可能需要代理或网络不通）"
                elif "RetryError" in err_str:
                    err_msg = "DuckDuckGo 多次重试失败（网络问题或被墙）"
                else:
                    err_msg = err_str[:200]
                print(f"❌ [SearchService] 所有搜索引擎均失败: Tavily/Bocha/DuckDuckGo。最终异常: {err_msg}")
                raise ValueError(f"搜索服务不可用: {err_msg}") from e

        return (
            {"status": "success", "data": results}
            if results
            else {
                "status": "success",
                "data": [],
                "message": "未找到相关结果。请尝试简化搜索词。",
            }
        )  # noqa: E501


# 导出全局单例
search_service = SearchService()
