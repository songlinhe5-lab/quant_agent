"""
MRKT-04: 市场复盘查询工具 — 供 Hermes Agent 调用

获取指定市场的每日收盘复盘报告，用于个股分析时的宏观判因上下文注入。
"""

from typing import Any, Dict

from hermes_agent.tool_registry import register_tool

from .base import BaseTool, get_backend_api_url
from .secure_client import SecureAsyncClient


@register_tool
class MarketReviewTool(BaseTool):
    """
    获取每日市场复盘报告（宏观大盘分析），用于个股判因时引用市场上下文。
    """

    name = "get_market_review"
    description = (
        "获取每日收盘后的市场复盘报告（A股/港股/美股），包含大盘指数、市场风格、资金流向、"
        "板块表现、关联事件、情绪评分和AI总结。用于个股分析时判断'是大盘系统性下跌还是个股问题'。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "market": {
                "type": "string",
                "enum": ["A股", "港股", "美股"],
                "description": "要查询的市场",
            },
            "date": {
                "type": "string",
                "description": "复盘日期 YYYY-MM-DD，不传则返回最新一份",
            },
            "days": {
                "type": "integer",
                "description": "获取最近N天复盘（用于多日趋势判断），默认1（仅最新）",
                "default": 1,
            },
        },
        "required": ["market"],
    }

    async def run(self, market: str, date: str = "", days: int = 1) -> Dict[str, Any]:
        backend_url = get_backend_api_url()

        async with SecureAsyncClient(timeout=15.0) as client:
            # 精确日期查询
            if date:
                url = f"{backend_url}/market-review/query"
                result = await self.rate_limit_aware_request(
                    client, "GET", url, params={"market": market, "date": date}
                )
            elif days > 1:
                # 多天趋势
                url = f"{backend_url}/market-review/recent"
                result = await self.rate_limit_aware_request(
                    client, "GET", url, params={"market": market, "days": days}
                )
            else:
                # 最新一份
                url = f"{backend_url}/market-review/latest"
                result = await self.rate_limit_aware_request(client, "GET", url, params={"market": market})

            if result.get("status") != "success":
                return result

            # 压缩输出：提取核心判因字段，减少 Token 消耗
            return self._compress_response(result, market)

    def _compress_response(self, result: Dict[str, Any], market: str) -> Dict[str, Any]:
        """压缩复盘数据，只保留判因核心字段"""
        data = result.get("data")
        if not data:
            return result

        # 单份 vs 多份
        if isinstance(data, list):
            compressed = [self._compress_single(r) for r in data]
            return {"status": "success", "market": market, "count": len(compressed), "reviews": compressed}

        return {"status": "success", "market": market, "review": self._compress_single(data)}

    def _compress_single(self, review: Dict[str, Any]) -> Dict[str, Any]:
        """压缩单份复盘"""
        return {
            "date": review.get("date"),
            "market": review.get("market"),
            "style": review.get("style"),
            "style_reasoning": review.get("style_reasoning"),
            "sentiment_score": review.get("sentiment_score"),
            "sentiment_level": review.get("sentiment_level"),
            "summary": review.get("summary"),
            "outlook": review.get("outlook"),
            "risk_tags": review.get("risk_tags", []),
            "capital_conclusion": (review.get("capital_flow") or {}).get("conclusion", ""),
            "indices": [
                {"name": i.get("name"), "close": i.get("close"), "change_pct": i.get("change_pct")}
                for i in review.get("indices", [])
            ],
            "key_events": [
                {"title": e.get("title"), "impact": e.get("impact")} for e in review.get("key_events", [])[:3]
            ],
            "event_impact_summary": review.get("event_impact_summary", ""),
        }
