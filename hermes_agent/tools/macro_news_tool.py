import os
from typing import Dict, Any
from datetime import datetime

from .base import BaseTool
from .secure_client import SecureAsyncClient
from hermes_agent.tool_registry import register_tool

@register_tool
class MacroNewsTool(BaseTool):
    """
    获取市场实时新闻与宏观舆情，用于撰写早报或大盘情绪分析。
    """
    name = "get_macro_news"
    description = "获取过去 24 小时内的全球宏观经济与金融市场新闻，用于新闻摘要、情绪分析与热点提取。"
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "需要获取的新闻条数。如果要查阅全天的新闻撰写全景早报，可设为 100 甚至 200。默认 50。"
            },
            "category": {
                "type": "string",
                "description": "新闻分类，默认为 general。可选：general, forex, crypto, merger"
            }
        }
    }

    async def run(self, limit: int = 50, category: str = "general") -> Dict[str, Any]:
        backend_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000")
        url = f"{backend_url}/macro/news"
        
        # RL-14: 限流感知智能重试
        async with SecureAsyncClient(timeout=15.0) as client:
            result = await self.rate_limit_aware_request(
                client, "GET", url, params={"limit": limit, "category": category}
            )
            
            if result.get("status") == "success":
                # 核心机制：压缩返回的数据结构，剥离无用的图片URL和ID，极大节省大模型阅读的 Token 成本
                compressed_news = []
                for item in result.get("data", []):
                    dt = datetime.fromtimestamp(item.get("datetime", 0)).strftime('%Y-%m-%d %H:%M:%S')
                    news_obj = {
                        "time": dt,
                        "headline": item.get("headline"),
                        "summary": item.get("summary")
                    }
                    if item.get("tags"):
                        news_obj["tags"] = item.get("tags")
                    compressed_news.append(news_obj)
                return {"status": "success", "count": len(compressed_news), "data": compressed_news}
            return result