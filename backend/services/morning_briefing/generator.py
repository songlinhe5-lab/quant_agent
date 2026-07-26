"""BRD-01: 盘前早报生成引擎

编排 4 个数据源工具 -> LLM 组装成严格遵循 AGENTS.md §7 早报模板的 Markdown:
  1. get_macro_calendar        -> 全球宏观高危雷达
  2. get_broker_market_data    -> 核心标的监控 (QUOTE)
  3. get_macro_news            -> 24h 宏观舆情提纯
  4. get_macro_sentiment_history -> 情绪风向标 (VIX / P/C / Credit Spread)

产物为可直接渲染的 Markdown 字符串，供前端预览 / 复制 / 分享。
复用 market_review 引擎的「并行采集 + 优雅降级 + LLM 组装」骨架，但产物形态不同。
"""

import asyncio
import json
import logging
import uuid
from datetime import date as date_cls
from typing import Optional

from hermes_agent.tool_registry import ToolRegistry
from backend.services.llm_service import LLMService, ModelTier
from backend.services.morning_briefing.models import BriefingResult
from backend.services.morning_briefing.storage import save_briefing

logger = logging.getLogger(__name__)

# 核心标的监控清单：按市场切换，避免"全球"清单硬套单一市场
MARKET_TICKERS: dict[str, list[str]] = {
    "全球": [
        "SPY", "QQQ", "DIA",      # 美股指数 ETF
        "GLD", "TLT",             # 黄金 / 美债
        "DXY", "USDCNH",          # 美元指数 / 离岸人民币
        "BTC",                    # 加密货币情绪锚
        "00700.HK", "600519.SH", "513100.SH",  # 港股 / A股 核心 + 纳指ETF
    ],
    "美股": [
        "SPY", "QQQ", "DIA", "IWM",   # 大盘 / 纳指 / 道指 / 罗素2000
        "GLD", "TLT",                 # 黄金 / 美债
        "DXY", "BTC",                 # 美元 / 加密情绪锚
        "NVDA", "AAPL", "TSLA",       # 龙头个股
    ],
    "港股": [
        "HSI", "HSCEI",               # 恒生指数 / 国企指数
        "00700.HK", "09988.HK", "03690.HK", "01810.HK",  # 腾讯/阿里/美团/小米
        "GLD", "DXY", "BTC",          # 黄金 / 美元 / 加密情绪锚
    ],
    "A股": [
        "000001.SH", "399001.SZ", "399006.SZ",  # 上证 / 深成 / 创业板指
        "600519.SH", "601318.SH", "300750.SZ",  # 茅台 / 平安 / 宁德
        "513100.SH", "518880.SH",               # 纳指ETF / 黄金ETF
    ],
}

SUPPORTED_MARKETS = list(MARKET_TICKERS.keys())


def get_tickers_for_market(market: str) -> list[str]:
    """按市场返回监控标的；未知市场回退到全球清单"""
    return MARKET_TICKERS.get(market, MARKET_TICKERS["全球"])

SOURCE_TOOLS = [
    "get_macro_calendar",
    "get_broker_market_data",
    "get_macro_news",
    "get_macro_sentiment_history",
]

SYSTEM_PROMPT = (
    "你是 Quant Agent 主脑——在华尔街摸爬滚打 20 年的顶尖量化交易老炮。"
    "你语言犀利、毒舌、充满金融黑话，用数据和逻辑说话，厌恶废话。"
    "你必须输出一份专业、硬核、可直接渲染的盘前早报 Markdown，"
    "中文金融术语精准，杜绝机器翻译腔。"
)

MORNING_BRIEFING_PROMPT = """请基于以下【真实数据】，生成 {market} 市场 {trade_date} 的盘前推演早报。
严格遵循下面的 Markdown 模板，不要输出模板以外的任何说明文字，直接给最终早报正文。

# 🌤️ Quant Agent 盘前推演早报

## 📅 全球宏观高危雷达 (未来 7 天)
- 对每条宏观事件输出: **[日期/时间] [国家]** [中文事件名称] (前值: X | 预期: Y)
  *风控推演: 一句话推演该事件可能引发的流动性风险或关注点*

## 📈 核心标的监控
- 对每个标的输出: **[代码]**: 最新价: [价格] | 涨跌幅: [百分比] | 成交量: [量]

## 🧠 主脑综合研判
- 先给「多空因素矩阵」Markdown 表格 (表头: 多头因素 ✅ | 空头因素 ❌)
- 再给量化概率: **看涨概率 (Bullish Probability):** [0-100 的整数]%
- 一句硬核毒舌核心结论与明确的交易建议 (持仓观望 / 等待回踩 / 设止损位等)

*(数据获取时间: {trade_date} 盘前, 数据来源: get_macro_calendar / get_broker_market_data / get_macro_news / get_macro_sentiment_history)*

=== 真实数据 ===
{data}
"""


class MorningBriefingGenerator:
    """盘前早报生成器"""

    def __init__(self, llm: Optional[LLMService] = None, tool_registry=None):
        self.llm = llm or LLMService()
        self.tool_registry = tool_registry or ToolRegistry()

    async def generate(
        self, market: str = "全球", target_date: Optional[str] = None
    ) -> BriefingResult:
        """生成一份盘前早报并持久化，返回带分享 ID 的结果"""
        trade_date = target_date or date_cls.today().strftime("%Y-%m-%d")
        logger.info(f"[Briefing] 开始生成 {market} {trade_date} 盘前早报")

        tickers = get_tickers_for_market(market)
        calendar, quotes, news, sentiment = await self._collect_data(market, tickers)
        markdown = await self._build_markdown(
            market, trade_date, calendar, quotes, news, sentiment
        )

        result = BriefingResult(
            id=uuid.uuid4().hex[:10],
            date=trade_date,
            market=market,
            markdown=markdown,
            source_tools=SOURCE_TOOLS,
        )
        await save_briefing(result)
        logger.info(f"[Briefing] 早报已生成 id={result.id} len={len(markdown)}")
        return result

    # ─── 数据采集 ────────────────────────────────────────────────
    async def _collect_data(self, market: str, tickers: list[str]):
        async def safe(name: str, coro):
            try:
                return await coro
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[Briefing] {name} 采集失败: {e}")
                return None

        calendar_t, quotes_t, news_t, sentiment_t = await asyncio.gather(
            safe(
                "get_macro_calendar",
                self.tool_registry.execute(
                    "get_macro_calendar", days_ahead=7, days_back=0
                ),
            ),
            safe(
                "get_broker_market_data",
                self.tool_registry.execute(
                    "get_broker_market_data", action="QUOTE", tickers=tickers
                ),
            ),
            safe("get_macro_news", self.tool_registry.execute("get_macro_news")),
            safe(
                "get_macro_sentiment_history",
                self.tool_registry.execute("get_macro_sentiment_history"),
            ),
        )
        return calendar_t, quotes_t, news_t, sentiment_t

    # ─── Markdown 组装 ──────────────────────────────────────────
    async def _build_markdown(
        self, market, trade_date, calendar, quotes, news, sentiment
    ) -> str:
        data_bundle = self._format_data_bundle(
            market, calendar, quotes, news, sentiment
        )
        prompt = MORNING_BRIEFING_PROMPT.format(
            market=market, trade_date=trade_date, data=data_bundle
        )
        try:
            markdown = await self.llm.generate(
                prompt, tier=ModelTier.STANDARD, system_prompt=SYSTEM_PROMPT
            )
            if not markdown or len(markdown.strip()) < 50:
                raise ValueError("LLM 返回内容过短，疑似空响应")
            return markdown.strip()
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Briefing] LLM 组装失败，启用数据兜底: {e}")
            return self._fallback_markdown(
                market, trade_date, calendar, quotes, news, sentiment
            )

    # ─── 数据精简 (喂给 LLM，控制 token) ────────────────────────
    def _format_data_bundle(self, market, calendar, quotes, news, sentiment) -> str:
        parts: list[str] = []
        max_quotes = len(get_tickers_for_market(market))

        if calendar:
            try:
                events = calendar.get("events") or calendar.get("data") or []
                lines = []
                for ev in events[:12]:
                    lines.append(
                        f"- {ev.get('time') or ev.get('date')} | {ev.get('country')} | "
                        f"{ev.get('title') or ev.get('name')} "
                        f"(前值:{ev.get('previous')} | 预期:{ev.get('forecast')})"
                    )
                if lines:
                    parts.append("【宏观日历】\n" + "\n".join(lines))
            except Exception:  # noqa: BLE001
                pass

        if quotes:
            try:
                qlist = quotes.get("data") or quotes.get("quotes") or quotes
                if isinstance(qlist, dict):
                    qlist = [qlist]
                lines = []
                for q in qlist[: max_quotes]:
                    lines.append(
                        f"- {q.get('symbol') or q.get('ticker')}: 价={q.get('last_price') or q.get('price')} "
                        f"涨跌幅={q.get('change_pct') or q.get('change_percent')} "
                        f"量={q.get('volume')}"
                    )
                if lines:
                    parts.append("【核心标的快照】\n" + "\n".join(lines))
            except Exception:  # noqa: BLE001
                pass

        if news:
            try:
                nlist = news.get("news") or news.get("data") or news
                if isinstance(nlist, dict):
                    nlist = [nlist]
                lines = []
                for n in nlist[:10]:
                    lines.append(
                        f"- {n.get('time') or ''} | {n.get('title')} | {n.get('summary') or ''}"
                    )
                if lines:
                    parts.append("【24h 宏观新闻】\n" + "\n".join(lines))
            except Exception:  # noqa: BLE001
                pass

        if sentiment:
            try:
                parts.append("【情绪序列】\n" + json.dumps(sentiment, ensure_ascii=False)[:1200])
            except Exception:  # noqa: BLE001
                pass

        return "\n\n".join(parts) if parts else "（数据源暂不可用，请基于主脑经验给出盘前研判）"

    # ─── LLM 失败兜底 (保证有产出) ──────────────────────────────
    def _fallback_markdown(self, market, trade_date, calendar, quotes, news, sentiment) -> str:
        return (
            f"# 🌤️ Quant Agent 盘前推演早报\n\n"
            f"> ⚠️ 数据引擎或 LLM 暂不可用，以下为降级版骨架，请以实时数据为准。\n\n"
            f"## 📅 全球宏观高危雷达 (未来 7 天)\n\n"
            f"_（宏观日历获取失败）_\n\n"
            f"## 📈 核心标的监控\n\n"
            f"_（行情快照获取失败）_\n\n"
            f"## 🧠 主脑综合研判\n\n"
            f"- 当前数据源异常，主脑拒绝在真空里瞎猜。等工具恢复再推演。\n\n"
            f"*(数据获取时间: {trade_date} 盘前, 数据来源: 降级模式)*"
        )


async def generate_morning_briefing(
    market: str = "全球", target_date: Optional[str] = None
) -> BriefingResult:
    """模块级便捷封装"""
    return await MorningBriefingGenerator().generate(market=market, target_date=target_date)
