"""搜索 / 网页抓取数据源实现（物理解耦裁剪版）

主服务经 DataSourceRouter HTTP 调 /api/v1/data (source=tavily|bocha|jina) 访问本实现。
统一在此持有外部 API key 与 rate limit，主服务不再直连 api.tavily.com / api.bochaai.com / r.jina.ai。
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class TavilyService:
    async def search(self, query: str, max_results: int = 5, **kw) -> dict[str, Any]:
        key = os.getenv("TAVILY_API_KEY")
        if not key:
            return {"status": "error", "message": "TAVILY_API_KEY 未配置"}
        payload = {"api_key": key, "query": query, "search_depth": "advanced", "max_results": max_results}
        payload.update({k: v for k, v in kw.items() if v is not None})
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                r = await c.post("https://api.tavily.com/search", json=payload)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Tavily request failed: {e}"}
        if r.status_code == 200:
            results = [
                {"title": i.get("title"), "href": i.get("url"), "body": i.get("content")}
                for i in r.json().get("results", [])
            ]
            return {"status": "success", "data": results}
        if r.status_code == 429:
            return {"status": "error", "message": "Tavily 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"Tavily HTTP {r.status_code}"}


class BochaService:
    async def search(self, query: str, max_results: int = 5, **kw) -> dict[str, Any]:
        key = os.getenv("BOCHA_API_KEY")
        if not key:
            return {"status": "error", "message": "BOCHA_API_KEY 未配置"}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {"query": query, "count": max_results}
        try:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post("https://api.bochaai.com/v1/web-search", headers=headers, json=payload)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Bocha request failed: {e}"}
        if r.status_code == 200:
            items = r.json().get("data", {}).get("webPages", {}).get("value", [])
            results = [{"title": i.get("name"), "href": i.get("url"), "body": i.get("snippet")} for i in items]
            return {"status": "success", "data": results}
        if r.status_code == 429:
            return {"status": "error", "message": "Bocha 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"Bocha HTTP {r.status_code}"}


class JinaService:
    async def scrape(self, url: str, api_key: str | None = None) -> dict[str, Any]:
        if not url.lower().startswith(("http://", "https://")):
            return {"status": "error", "message": "Jina 仅允许 http(s) 协议"}
        key = api_key or os.getenv("JINA_API_KEY")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
                r = await c.get(f"https://r.jina.ai/{url}", headers=headers)
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"Jina request failed: {e}"}
        if r.status_code == 200:
            content = r.text
            if len(content) < 50 or "Just a moment" in content:
                return {"status": "error", "message": "Jina 返回内容过短或触发反爬"}
            return {"status": "success", "data": {"url": url, "content": content}}
        if r.status_code == 429:
            return {"status": "error", "message": "Jina 429 rate limited", "error_category": "rate_limit"}
        return {"status": "error", "message": f"Jina HTTP {r.status_code}"}


tavily_service = TavilyService()
bocha_service = BochaService()
jina_service = JinaService()
