from datetime import datetime, timezone
from typing import Any, Dict

from hermes_agent.tool_registry import register_tool


@register_tool(scopes=["news"])  # 个股公告与新闻舆情
class GetCompanyNewsTool:
    name = "get_company_news"
    description = "获取指定公司的近期个股新闻与公告，自带 AI 情感打分与中文摘要。适用于分析某只股票的基本面、近期舆情、财报发布及突发事件。"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码，必须包含市场前缀以明确区分，例如 'US.AAPL', 'HK.0700', 'SH.600519'",
            },
            "days_back": {
                "type": "integer",
                "description": "回溯天数，默认 3 天。可根据需要分析的时间跨度调整，例如 1, 3, 7",
                "default": 3,
            },
        },
        "required": ["ticker"],
    }

    async def run(self, ticker: str, days_back: int = 3) -> Dict[str, Any]:
        from backend.services.datasource.business import data_service
        from backend.services.macro.sentiment_service import sentiment_service

        try:
            # BE-ARCH-06b: 经 Facade 统一选源（自动按市场路由到 futu/finnhub/akshare）
            result = await data_service.get_company_news(ticker=ticker, days_back=days_back)

            if result.is_success and result.data:
                raw_news = result.data if isinstance(result.data, list) else []

                # 💡 判断市场类型以决定是否需要 LLM 提纯
                ticker_upper = ticker.upper()
                is_hk_stock = "HK" in ticker_upper or (ticker.isdigit() and len(ticker) == 5)
                is_a_stock = any(x in ticker_upper for x in ["SH", "SZ"]) or (ticker.isdigit() and len(ticker) == 6)

                # 💡 新增：仅针对 A 股/港股新闻源进行 LLM 提纯
                purified_news = raw_news
                if is_a_stock or is_hk_stock:
                    purified_news = await sentiment_service.batch_filter_news(raw_news)

                compressed_news = []

                # 仅截取最新的 15 条核心新闻
                for item in purified_news[:15]:
                    dt_val = item.get("datetime", 0)
                    try:
                        dt = datetime.fromtimestamp(float(dt_val), timezone.utc)
                        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        date_str = item.get("date", str(dt_val))
                    compressed_news.append(
                        {
                            "date": item.get("date", date_str),
                            "headline": item.get("headline", ""),
                            "summary": item.get("summary", ""),
                        }
                    )

                # 💡 并发调用大模型，给提取出的每条精简新闻打上情感分和中文翻译
                scored_news = await sentiment_service.batch_analyze_news(compressed_news)

                return {
                    "status": "success",
                    "data": scored_news,
                    "message": f"已成功获取并截取最近 {len(scored_news)} 条核心新闻，且已完成 AI 情感多空打分供研判。",
                    "total_found": len(raw_news),
                    "source": result.source,
                }

            return {"status": "error", "message": result.error.message if result.error else "获取个股新闻失败"}
        except Exception as e:
            return {"status": "error", "message": f"获取个股新闻失败: {e}"}
