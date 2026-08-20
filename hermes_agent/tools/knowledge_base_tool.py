import asyncio
import time
from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool


@register_tool
class KnowledgeBaseTool(BaseTool):
    """
    全局知识库检索工具。
    在不提供具体 URL 的情况下，根据查询词检索系统已经读取并持久化在 PostgreSQL pgvector 里的所有历史网页/研报碎片。
    """

    name = "search_global_knowledge"
    description = "全局知识库检索。当用户问及'你之前读过的某篇研报'或'提取历史资料中关于某某的信息'时调用。该工具会在系统已经持久化的所有网页碎片中进行语义搜索，并返回最相关的段落及其原文出处(URL)。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "需要在全局知识库中语义检索的查询问题，越详细越好（例如：'苹果对于大中华区营收的最新指引是多少？'）",
            },
            "limit": {"type": "integer", "description": "返回的最多相关片段数量，默认为 5", "default": 5},
            "days_back": {
                "type": "integer",
                "description": "可选参数：时间过滤。指定检索过去 N 天内的数据（例如 30 表示只检索最近 30 天抓取的文献）。如果不填或为 0，则检索所有历史数据。",
                "default": 0,
            },
        },
        "required": ["query"],
    }

    async def run(self, query: str, limit: int = 5, days_back: int = 0) -> Dict[str, Any]:
        if not query:
            return {"status": "error", "message": "查询问题不能为空"}

        try:
            summary = await asyncio.to_thread(self._search_pg, query, limit, days_back)
            missed = summary.startswith("未能在全局知识库中检索到")
            if not missed:
                return {
                    "status": "success",
                    "data": {"query": query, "content": summary},
                    "skip_cache": False,
                }
            # 💡 本地知识库未命中：联动 web_search 兜底，避免对「未持久化的研报/资讯」返回空。
            #    用户查询如个股研报（目标价/盈利预测）时, 知识库通常未存过, 联网搜索才能拿到。
            fallback = await self._fallback_web_search(query, limit)
            if fallback is not None:
                return {
                    "status": "success",
                    "data": {"query": query, "content": fallback},
                    "skip_cache": True,  # 兜底结果不落长期缓存
                    "source": "web_search_fallback",
                }
            # web_search 也不可用时, 返回原 miss 提示并引导
            return {
                "status": "success",
                "data": {"query": query, "content": summary},
                "skip_cache": True,
            }
        except Exception as e:
            return {"status": "error", "message": f"全局知识库检索失败: {str(e)}"}

    async def _fallback_web_search(self, query: str, limit: int) -> str | None:
        """本地知识库未命中时, 经 web_search 联网兜底 (DuckDuckGo → 后端搜索网关)。"""
        try:
            from .web_search_tool import WebSearchTool

            res = await WebSearchTool().run(query, max_results=limit)
            if res.get("status") != "success" or not res.get("data"):
                return None
            hits = res["data"]
            if not isinstance(hits, list) or not hits:
                return None
            # 每个 hit 可能是 dict 或 str
            parts = ["🌐 全局知识库未命中，以下为网络搜索兜底结果（建议结合 download_report 下载研报后解析）：\n"]
            for i, h in enumerate(hits[:limit]):
                if isinstance(h, dict):
                    title = h.get("title") or h.get("headline") or h.get("url") or ""
                    url = h.get("url") or h.get("link") or ""
                    snippet = h.get("snippet") or h.get("summary") or ""
                    parts.append(f"[{i + 1}] {title}\n{snippet}\n(🔗 {url})")
                else:
                    parts.append(f"[{i + 1}] {h}")
                parts.append("")
            return "\n".join(parts).strip()
        except Exception:
            return None

    def _search_pg(self, query: str, limit: int, days_back: int) -> str:
        """从 PostgreSQL pgvector (WebpageKnowledgeBase) 语义检索全局历史知识库。

        与 fetch_webpage 写入共用 backend.core.embeddings.get_embeddings，向量空间一致。
        """
        try:
            from sqlalchemy import text as _text

            from backend.core.database import SessionLocal
            from backend.core.embeddings import get_embeddings
        except ImportError as e:
            return f"⚠️ 知识库检索依赖缺失: {e}"

        if not query:
            return "查询问题不能为空。"

        query_vec = get_embeddings([query])
        if not query_vec:
            return "⚠️ Embedding 服务不可用，无法生成查询向量。"

        # 时间过滤: days_back > 0 时只检索最近 N 天
        time_filter = ""
        params: dict = {"q": str(query_vec[0]), "limit": limit}
        if days_back and days_back > 0:
            cutoff = int(time.time()) - (days_back * 24 * 3600)
            time_filter = "AND timestamp >= :cutoff"
            params["cutoff"] = cutoff

        sql = _text(
            f"""
            SELECT content, url, 1 - (embedding <=> :q) AS score
            FROM webpage_knowledge_base
            WHERE 1=1 {time_filter}
            ORDER BY embedding <=> :q
            LIMIT :limit
            """
        )

        try:
            with SessionLocal() as db:
                rows = db.execute(sql, params).fetchall()
        except Exception as e:
            return f"⚠️ 全局知识库检索失败: {e}"

        if not rows:
            return f"未能在全局知识库中检索到与 '{query}' 高度相关的内容。"

        summary = f"🎯 根据查询 '{query}'，在全局历史知识库中跨文档检索到以下 {len(rows)} 个相关片段：\n\n"
        for i, row in enumerate(rows):
            doc = row[0]
            url = row[1]
            score = row[2]
            summary += f"[{i + 1}] 【相关度: {score:.3f}】\n{doc}\n(🔗 来源链接: {url})\n\n"

        summary += "(💡 RAG 知识库提示：1. 如果以上片段存在数据矛盾，请明确指出冲突并自行推断，严禁强行掩盖。 2. 在组织回答时，必须像学术论文一样，在你陈述的事实或数据后，严格使用对应的序号进行内联引用标注，并在回答的最后附上「📚 参考文献」列表展示所有被引用的片段序号、对应标题和来源链接。)"
        return summary.strip()
