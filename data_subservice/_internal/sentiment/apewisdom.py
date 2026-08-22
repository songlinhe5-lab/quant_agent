"""ApeWisdom 散户社交媒体热度数据源（独立 sentiment 源，非并入 search）。

端点（实测免费、无需 Key）：
    GET https://apewisdom.io/api/v1.0/filter/{filter}/page/{n}
    {filter} ∈ reddit, stocktwits, twitter, yahoo, all
    {n} 页码，每页 100 条

返回字段（page 内 data 数组元素）：
    rank / ticker / name / mentions（提及数）/ upvotes（点赞）
    rank_24h_ago / mentions_24h_ago（24h 前环比基准）

错误语义对齐 finnhub 叶子节点：429 → rate_limit，其余 → 普通 error。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from data_subservice._internal.logger import logger

_BASE = "https://apewisdom.io/api/v1.0"
_TIMEOUT = float(os.getenv("APEWISDOM_TIMEOUT", "10"))
_DEFAULT_PAGE_SIZE = 100
_MAX_PAGES = int(os.getenv("APEWISDOM_MAX_PAGES", "11"))  # ApeWisdom 约 11 页 × 100 条
_VALID_FILTERS = {"reddit", "stocktwits", "twitter", "yahoo", "all"}


def _normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """归一化单条热度数据，统一字段名 + 计算 24h 环比突变率。

    热度因子（A 线）：mentions 环比 (mentions - mentions_24h_ago) / mentions_24h_ago
    → 「散户注意力突变」。缺失基准时记为 None，避免除零。
    """
    mentions = raw.get("mentions")
    mentions_24h = raw.get("mentions_24h_ago")
    delta_pct = None
    if mentions is not None and mentions_24h not in (None, 0):
        delta_pct = round((mentions - mentions_24h) / mentions_24h, 4)
    return {
        "rank": raw.get("rank"),
        "ticker": raw.get("ticker"),
        "name": raw.get("name"),
        "mentions": mentions,
        "upvotes": raw.get("upvotes"),
        "rank_24h_ago": raw.get("rank_24h_ago"),
        "mentions_24h_ago": mentions_24h,
        "mentions_delta_pct": delta_pct,
    }


class ApeWisdomService:
    """ApeWisdom 底层 REST 客户端（子服务叶子节点）。"""

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """复用 httpx.AsyncClient，带超时 + 429 兜底。

        返回统一 dict：成功含 data/page/source；失败含 status=error + error_category。
        """
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                r = await client.get(f"{_BASE}{path}", params=params or {})
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [ApeWisdom] 请求失败 {path}: {e}")
            return {"status": "error", "message": f"ApeWisdom request failed: {e}"}
        if r.status_code == 429:
            return {"status": "error", "message": "ApeWisdom 429 rate limited", "error_category": "rate_limit"}
        if r.status_code >= 400:
            return {"status": "error", "message": f"ApeWisdom HTTP {r.status_code}"}
        try:
            payload = r.json()
        except Exception as e:  # noqa: BLE001
            return {"status": "error", "message": f"ApeWisdom 响应解析失败: {e}"}
        return {"status": "success", "data": payload}

    async def get_trending(
        self,
        filter: str = "all",
        page: int = 1,
        page_size: int = _DEFAULT_PAGE_SIZE,
        top_n: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取热度榜单页（或 top N 全量）。

        - filter: reddit/stocktwits/twitter/yahoo/all
        - page: 页码（从 1 起）
        - top_n: 若提供，则自动翻页抓取到累计 ≥ top_n 条后截断（受 _MAX_PAGES 限）
        """
        if filter not in _VALID_FILTERS:
            return {"status": "error", "message": f"无效的 filter: {filter}，可选 {sorted(_VALID_FILTERS)}"}
        if page < 1:
            return {"status": "error", "message": "page 必须从 1 起"}

        collected: List[Dict[str, Any]] = []
        pages_to_fetch = 1
        if top_n is not None:
            pages_to_fetch = min(_MAX_PAGES, (top_n + page_size - 1) // page_size)

        for p in range(page, page + pages_to_fetch):
            resp = await self._get(f"/filter/{filter}/page/{p}")
            if resp.get("status") != "success":
                # 翻页中途失败：返回已收集部分 + 错误上下文
                resp["collected"] = [_normalize_item(x) for x in collected]
                return resp
            page_data = resp["data"].get("data", [])
            if not page_data:
                break
            collected.extend(page_data)
            if top_n is not None and len(collected) >= top_n:
                break

        items = [_normalize_item(x) for x in collected]
        if top_n is not None:
            items = items[:top_n]
        return {
            "status": "success",
            "source": "apewisdom",
            "filter": filter,
            "page": page,
            "count": len(items),
            "data": items,
        }


apewisdom_service = ApeWisdomService()
