from typing import Any, Dict, List, Optional

from backend.services.datasource.router import data_source_router

# BE-ARCH-07d: 主服务不再直连外部搜索 API (api.tavily.com / api.bochaai.com /
# duckduckgo_search)。统一经 DataSourceRouter HTTP 代理调 data_subservice 子服务的
# search_worker 远程代理, 由子服务持有 key / rate limit / 降级调度。

# 降级优先级: Tavily -> Bocha (子服务侧可继续扩展 DuckDuckGo 免费兜底)
_SEARCH_SOURCE_PRIORITY: List[str] = ["tavily", "bocha"]


class SearchService:
    """
    统一网页搜索服务 (BE-ARCH-07d 合规: 仅远程代理)。

    主服务不再直连任何外部搜索 API, 按优先级经 DataSourceRouter 调子服务
    search_worker 的 SEARCH action (Tavily API -> Bocha API 降级)。
    """

    async def web_search(
        self,
        query: str,
        max_results: int = 5,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:  # noqa: E501
        last_err: str = ""
        for source in _SEARCH_SOURCE_PRIORITY:
            try:
                resp = await data_source_router.fetch_search(
                    source,
                    query=query,
                    max_results=max_results,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
            except Exception as e:  # noqa: BLE001 - 远程代理异常视为该源不可用, 尝试下一源
                last_err = str(e)
                continue

            if isinstance(resp, dict) and resp.get("status") == "success":
                data = resp.get("data") or []
                if data:
                    return {"status": "success", "data": data}
                last_err = resp.get("message", f"{source} 返回空结果")

        # 全部源失败/无结果
        if last_err:
            print(f"⚠️ [SearchService] 所有远程搜索源均失败, 末次错误: {last_err}")
        return {
            "status": "success",
            "data": [],
            "message": "未找到相关结果或搜索服务暂不可用。请尝试简化搜索词。",
        }


# 导出全局单例
search_service = SearchService()
