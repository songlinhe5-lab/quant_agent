from datetime import datetime, timezone
from typing import Any, Dict

from backend.services.akshare_service import akshare_service
from backend.services.finnhub_service import finnhub_service
from backend.services.sentiment_service import sentiment_service
from hermes_agent.tool_registry import register_tool


@register_tool
class GetCompanyNewsTool:
    name = "get_company_news"
    description = "获取指定公司的近期个股新闻与公告，自带 AI 情感打分与中文摘要。适用于分析某只股票的基本面、近期舆情、财报发布及突发事件。"
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "股票代码，必须包含市场前缀以明确区分，例如 'US.AAPL', 'HK.0700', 'SH.600519'"
            },
            "days_back": {
                "type": "integer",
                "description": "回溯天数，默认 3 天。可根据需要分析的时间跨度调整，例如 1, 3, 7",
                "default": 3
            }
        },
        "required": ["ticker"]
    }

    async def run(self, ticker: str, days_back: int = 3) -> Dict[str, Any]:
        try:
            # 💡 智能路由：港股走雅虎财经，A 股走 AKShare (东财)，美股走 Finnhub
            ticker_upper = ticker.upper()
            is_hk_stock = "HK" in ticker_upper or (ticker.isdigit() and len(ticker) == 5)
            is_a_stock = any(x in ticker_upper for x in ["SH", "SZ"]) or (ticker.isdigit() and len(ticker) == 6)

            if is_hk_stock:
                # 将 HK.0772 格式化为雅虎财经需要的 0772.HK
                yf_sym = ticker_upper
                if yf_sym.startswith("HK."):
                    yf_sym = f"{yf_sym[3:]}.HK"
                elif yf_sym.isdigit():
                    yf_sym = f"{yf_sym}.HK"

                yahoo_news = await finnhub_service._fallback_yahoo_news(yf_sym)
                res = {"status": "success", "data": yahoo_news}
            elif is_a_stock:
                res = await akshare_service.get_company_news(ticker=ticker)
            else:
                res = await finnhub_service.get_company_news(ticker=ticker, days_back=days_back)

            # 💡 数据瘦身：防止原始的几十条带有巨长 URL 和冗余字段的 JSON 撑爆大模型的 Token 上限
            if res.get("status") == "success" and "data" in res:
                raw_news = res["data"]

                # 💡 新增：仅针对 A 股/港股新闻源进行 LLM 提纯，因为 Finnhub 新闻质量较高
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
                    compressed_news.append({
                        "date": item.get("date", date_str),
                        "headline": item.get("headline", ""),
                        "summary": item.get("summary", "")
                    })

                # 💡 并发调用大模型，给提取出的每条精简新闻打上情感分和中文翻译
                scored_news = await sentiment_service.batch_analyze_news(compressed_news)

                res["data"] = scored_news
                res["message"] = f"已成功获取并截取最近 {len(scored_news)} 条核心新闻，且已完成 AI 情感多空打分供研判。"
                res["total_found"] = len(raw_news)

            return res
        except Exception as e:
            return {"status": "error", "message": f"获取个股新闻失败: {e}"}
