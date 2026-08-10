"""搜索 / 网页抓取 worker（子服务叶子节点）。

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=tavily|bocha|jina) 访问本 worker。
统一在此代理外部搜索/抓取 API，主服务不再直连外部 API。
"""

from __future__ import annotations

from typing import Any

from data_subservice._internal.logger import logger
from data_subservice._internal.search import (
    bocha_service,
    jina_service,
    tavily_service,
)


async def handle_search(source: str, action: str, params: dict[str, Any]) -> dict[str, Any]:
    src = source.lower()
    if src == "tavily":
        if action != "SEARCH":
            return {"error": f"unknown tavily action: {action}"}
        return await tavily_service.search(
            query=str(params.get("query", "")),
            max_results=int(params.get("max_results", 5)),
            include_domains=params.get("include_domains"),
            exclude_domains=params.get("exclude_domains"),
        )
    if src == "bocha":
        if action != "SEARCH":
            return {"error": f"unknown bocha action: {action}"}
        return await bocha_service.search(
            query=str(params.get("query", "")),
            max_results=int(params.get("max_results", 5)),
        )
    if src == "jina":
        if action != "SEARCH":
            return {"error": f"unknown jina action: {action}"}
        return await jina_service.scrape(url=str(params.get("url", "")))
    if src == "search":
        # BE-ARCH-07d: 聚合搜索入口, 子服务侧接管原主服务的多源降级调度
        # (Tavily -> Bocha)。DuckDuckGo 免费兜底可在此扩展。
        return await _web_search_aggregated(params)
    return {"error": f"unknown search source: {source}"}


async def _web_search_aggregated(params: dict[str, Any]) -> dict[str, Any]:
    """子服务侧聚合降级: Tavily -> Bocha。首个成功且非空即返回。"""
    query = str(params.get("query", ""))
    max_results = int(params.get("max_results", 5))
    include_domains = params.get("include_domains")
    exclude_domains = params.get("exclude_domains")

    for svc in (tavily_service, bocha_service):
        try:
            resp = await svc.search(
                query=query,
                max_results=max_results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Search-worker] {svc.__class__.__name__} 失败: {e}")
            continue
        if isinstance(resp, dict) and resp.get("status") == "success" and resp.get("data"):
            return resp
    return {"status": "success", "data": [], "message": "未找到相关结果"}


async def startup() -> None:
    logger.info("[Search-worker] 初始化完成 (Tavily/Bocha/Jina 外部 API 代理就绪)")
