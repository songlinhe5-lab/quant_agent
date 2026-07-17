import asyncio
from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool


@register_tool
class DeleteKnowledgeTool(BaseTool):
    """
    全局知识库清理工具。
    根据特定的 URL 从 ChromaDB 中永久删除相关的网页碎片。
    """
    name = "delete_global_knowledge"
    description = "从全局知识库中删除指定 URL 的所有相关网页片段。当你在检索时发现某些网页数据（如旧财报、过时的指引）已经过期，并对当前的分析产生干扰时，主动调用此工具将其从向量数据库中永久清理。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "需要从知识库中删除的具体网页 URL 链接"
            }
        },
        "required": ["url"]
    }

    async def run(self, url: str) -> Dict[str, Any]:
        if not url:
            return {"status": "error", "message": "URL 不能为空"}

        try:
            result = await asyncio.to_thread(self._delete_chroma, url)
            return {"status": "success", "message": result}
        except Exception as e:
            return {"status": "error", "message": f"全局知识库清理失败: {str(e)}"}

    def _delete_chroma(self, url: str) -> str:
        from backend.core.database import SessionLocal
        from backend.core.models import WebpageKnowledgeBase

        with SessionLocal() as db:
            # 💡 直接通过关系型数据库进行精准的行级删除，彻底摆脱单机文件存储限制
            deleted_count = db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.url == url).delete()
            db.commit()

            if deleted_count > 0:
                return f"成功从全局云端知识库(PGVector)中删除了 {deleted_count} 个与 {url} 相关的片段缓存。"
            return "知识库中未找到需要清理的数据。"
