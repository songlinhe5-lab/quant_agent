import os
import asyncio
import time
from typing import Dict, Any

from .base import BaseTool
from hermes_agent.tool_registry import register_tool

@register_tool
class KnowledgeBaseTool(BaseTool):
    """
    全局知识库检索工具。
    在不提供具体 URL 的情况下，根据查询词检索系统已经读取并持久化在 ChromaDB 里的所有历史网页/研报碎片。
    """
    name = "search_global_knowledge"
    description = "全局知识库检索。当用户问及'你之前读过的某篇研报'或'提取历史资料中关于某某的信息'时调用。该工具会在系统已经持久化的所有网页碎片中进行语义搜索，并返回最相关的段落及其原文出处(URL)。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string", 
                "description": "需要在全局知识库中语义检索的查询问题，越详细越好（例如：'苹果对于大中华区营收的最新指引是多少？'）"
            },
            "limit": {
                "type": "integer",
                "description": "返回的最多相关片段数量，默认为 5",
                "default": 5
            },
            "days_back": {
                "type": "integer",
                "description": "可选参数：时间过滤。指定检索过去 N 天内的数据（例如 30 表示只检索最近 30 天抓取的文献）。如果不填或为 0，则检索所有历史数据。",
                "default": 0
            }
        },
        "required": ["query"]
    }

    async def run(self, query: str, limit: int = 5, days_back: int = 0) -> Dict[str, Any]:
        if not query:
            return {"status": "error", "message": "查询问题不能为空"}

        try:
            summary = await asyncio.to_thread(self._search_chroma, query, limit, days_back)
            return {"status": "success", "data": {"query": query, "content": summary}}
        except Exception as e:
            return {"status": "error", "message": f"全局知识库检索失败: {str(e)}"}

    def _search_chroma(self, query: str, limit: int, days_back: int) -> str:
        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError:
            return "⚠️ 缺少 chromadb 依赖，无法进行知识库检索。"

        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "chroma_db"))
        if not os.path.exists(db_path):
            return "本地知识库为空，暂无持久化的历史网页数据。"

        client = chromadb.PersistentClient(path=db_path)
        
        emb_api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        if emb_api_key:
            emb_base_url = os.getenv("EMBEDDING_BASE_URL")
            emb_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            emb_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=emb_api_key, model_name=emb_model, api_base=emb_base_url
            )
        else:
            emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-MiniLM-L12-v2")
            
        try:
            collection = client.get_collection(name="webpage_knowledge_base", embedding_function=emb_fn)  # type: ignore
        except Exception:
            return "全局知识库 (webpage_knowledge_base) 不存在或为空，说明系统之前还未成功抓取并持久化过任何长文。"

        # 构建 ChromaDB 元数据时间过滤器
        where_filter: Any = None
        if days_back > 0:
            cutoff = int(time.time()) - (days_back * 24 * 3600)
            where_filter = {"timestamp": {"$gte": cutoff}}  # 过滤出大于等于截止时间的数据

        # 根据 Query 和 时间条件 进行全局语义检索
        results = collection.query(query_texts=[query], n_results=limit, where=where_filter)
        
        docs = results.get("documents")
        metas = results.get("metadatas")
        
        if not docs or not docs[0]:
            return f"未能在全局知识库中检索到与 '{query}' 高度相关的内容。"
            
        summary = f"🎯 根据查询 '{query}'，在全局历史知识库中跨文档检索到以下 {len(docs[0])} 个相关片段：\n\n"
        safe_metas = metas[0] if metas and metas[0] else [{}] * len(docs[0])
        
        for i, (doc, meta) in enumerate(zip(docs[0], safe_metas)):
            meta = meta or {}
            headers = " > ".join([str(v) for k, v in meta.items() if str(k).startswith("Header")])
            title = f"[{i+1}] 【章节: {headers}】" if headers else f"[{i+1}] 【无标题片段】"
            url = meta.get("url", "未知来源")
            # 在每一段的下方显式附上其 URL 来源出处
            summary += f"{title}\n{doc}\n(🔗 来源链接: {url})\n\n"
            
        summary += "(💡 RAG 知识库提示：1. 如果以上片段存在数据矛盾，请明确指出冲突并自行推断，严禁强行掩盖。 2. 在组织回答时，必须像学术论文一样，在你陈述的事实或数据后，严格使用对应的序号进行内联引用标注，并在回答的最后附上「📚 参考文献」列表展示所有被引用的片段序号、对应标题和来源链接。)"
        return summary.strip()