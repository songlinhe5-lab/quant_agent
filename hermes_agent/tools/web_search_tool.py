from typing import Any, Dict, List, Optional

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool(scopes=["search"])  # 网络搜索 + 网页摘要
class WebSearchTool(BaseTool):
    """
    DuckDuckGo 互联网搜索工具
    """

    name = "web_search"
    description = "使用 DuckDuckGo 搜索引擎在互联网上获取最新资讯。当用户询问最新新闻、业绩预告、研报或底层 API 无法提供的实时信息时，必须调用此工具。"

    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要搜索的搜索词，例如：'A股 今日 业绩预增 公告'"},
            "max_results": {"type": "integer", "description": "返回的最大结果数量，默认为 5"},
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：指定要限制搜索的特定网站域名列表，例如 ['bloomberg.com', 'wsj.com', 'sec.gov']。如果不填则在全网搜索。",
            },
            "exclude_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "可选：指定要排除的特定网站域名列表，屏蔽内容农场或特定平台，例如 ['reddit.com', 'zhihu.com']。",
            },
        },
        "required": ["query"],
    }

    async def run(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # 利用 BaseTool 提供的方法设定搜索结果的缓存（1 小时），防止重复搜索浪费网络与触发限流
        domains_str = "_".join(include_domains) if include_domains else "all"
        exclude_str = "_".join(exclude_domains) if exclude_domains else "none"
        cache_key = f"web_search_{query}_{max_results}_{domains_str}_ex_{exclude_str}"
        cached = await self.get_cached_data(cache_key, ttl=3600)
        if cached:
            return cached

        base_url = get_backend_api_url()

        url = f"{base_url}/search/web"
        payload = {
            "query": query,
            "max_results": max_results,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
        }

        try:
            # 使用受限的内网安全客户端，保证 Tool 的架构纯洁性
            async with SecureAsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)
                # 💡 提取后端返回的详细错误信息，而非仅抛出 HTTP 状态码
                if resp.status_code != 200:
                    err_msg = resp.text
                    try:
                        body = resp.json()
                        err_msg = body.get("msg") or body.get("detail") or resp.text
                    except Exception:
                        pass
                    return {"status": "error", "message": f"搜索服务失败 (HTTP {resp.status_code}): {err_msg}"}
                res = resp.json()
                # 后端 API 统一响应封装为 {code, msg, data}，需先剥信封取出真实负载，
                # 否则下方对 status/data 的判断会全部落空（status 藏在 res["data"] 里），
                # 导致 WebScrapeTool 的降级搜索链路误判为失败。
                payload = res.get("data") if isinstance(res, dict) and "data" in res else res
                if isinstance(payload, dict) and payload.get("status") == "success" and payload.get("data"):
                    await self.set_cached_data(cache_key, payload, persist=True, ttl=3600)
                return payload
        except Exception as e:
            return {"status": "error", "message": f"请求后端搜索网关异常: {str(e)}"}
