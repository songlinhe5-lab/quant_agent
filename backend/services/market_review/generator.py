"""
MRKT-02: 宏观市场复盘生成引擎

流程: 数据采集 → LLM 结构化分析 → 组装 MarketDailyReview → 持久化
"""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.services.llm_service import ModelTier, llm_service
from backend.services.market_review.models import (
    CapitalFlow,
    IndexSnapshot,
    MarketDailyReview,
    MarketEvent,
    MarketStyle,
    MarketType,
    SectorPerformance,
    SentimentLevel,
)
from backend.services.market_review.storage import save_market_review
from hermes_agent.tool_registry import ToolRegistry

# ── 各市场核心指数映射 ──────────────────────────────────────────────────────
_MARKET_INDICES: dict[MarketType, list[dict[str, str]]] = {
    MarketType.A_SHARE: [
        {"code": "SH.000001", "name": "上证指数"},
        {"code": "SZ.399001", "name": "深证成指"},
        {"code": "SZ.399006", "name": "创业板指"},
    ],
    MarketType.HK: [
        {"code": "HK.800000", "name": "恒生指数"},
        {"code": "HK.800100", "name": "恒生科技指数"},
    ],
    MarketType.US: [
        {"code": "US..DJI", "name": "道琼斯工业"},
        {"code": "US..IXIC", "name": "纳斯达克综合"},
        {"code": "US..INX", "name": "标普500"},
    ],
}

# 板块涨跌代理 ETF：行情里无直接「板块指数」工具，用流动性好的行业 ETF 作板块表现代理
# （与 macro.py 大类资产思路一致）。A 股/美股用成熟行业 ETF，港股用代表性行业 ETF 作 best-effort 代理。
_SECTOR_ETFS: dict[MarketType, list[dict[str, str]]] = {
    MarketType.A_SHARE: [
        {"code": "SH.512480", "name": "半导体"},
        {"code": "SH.512010", "name": "医药"},
        {"code": "SZ.159930", "name": "能源"},
        {"code": "SH.512000", "name": "券商"},
        {"code": "SH.512800", "name": "银行"},
        {"code": "SZ.159928", "name": "消费"},
        {"code": "SH.512660", "name": "军工"},
        {"code": "SH.515030", "name": "新能源车"},
    ],
    MarketType.HK: [
        {"code": "HK.03033", "name": "恒生科技"},
        {"code": "HK.02800", "name": "蓝筹(恒指)"},
        {"code": "HK.03067", "name": "恒生科技(三星)"},
        {"code": "HK.02828", "name": "国企指数"},
        {"code": "HK.03038", "name": "恒生医疗"},
        {"code": "HK.03024", "name": "恒生消费"},
    ],
    MarketType.US: [
        {"code": "US.XLK", "name": "科技"},
        {"code": "US.XLE", "name": "能源"},
        {"code": "US.XLF", "name": "金融"},
        {"code": "US.XLV", "name": "医疗"},
        {"code": "US.XLI", "name": "工业"},
        {"code": "US.XLY", "name": "可选消费"},
        {"code": "US.XLP", "name": "必选消费"},
        {"code": "US.XLU", "name": "公用事业"},
        {"code": "US.XLRE", "name": "房地产"},
        {"code": "US.XLB", "name": "材料"},
        {"code": "US.XLC", "name": "通信"},
    ],
}


# 单工具采集超时
_COLLECT_TIMEOUT = 30.0


# ── LLM 结构化输出模型 ──────────────────────────────────────────────────────
class _LLMReviewAnalysis(BaseModel):
    """LLM 生成的复盘分析结构"""

    style: str = Field(description="市场风格: 大盘价值/大盘成长/小盘价值/小盘成长/均衡轮动/防御避险/投机炒作")
    style_reasoning: str = Field(description="风格判定依据，1-2句话")
    capital_conclusion: str = Field(description="资金面结论，如'外资主导买入科技，内资撤离消费'")
    sentiment_score: int = Field(ge=0, le=100, description="情绪评分 0(极度恐惧)~100(极度贪婪)")
    sentiment_level: str = Field(description="情绪等级: 极度恐惧/恐惧/中性/贪婪/极度贪婪")
    event_impact_summary: str = Field(description="事件对市场综合影响，1-2句话")
    summary: str = Field(description="3-5句话概括当日市场核心走势与驱动因素")
    outlook: str = Field(description="次日/短期展望，含关键风险点")
    risk_tags: list[str] = Field(default_factory=list, description="风险标签列表，如['系统性回调','板块轮动']")
    key_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="从新闻中提取的关键事件 [{title, category, impact, affected_sectors}]",
    )


# ── 数据采集 ────────────────────────────────────────────────────────────────
async def _collect_index_quotes(registry: ToolRegistry, market: MarketType) -> list[IndexSnapshot]:
    """并行采集市场核心指数行情"""
    indices_cfg = _MARKET_INDICES.get(market, [])
    if not indices_cfg:
        return []

    async def _fetch_one(cfg: dict[str, str]) -> Optional[IndexSnapshot]:
        try:
            result = await asyncio.wait_for(
                registry.execute("get_broker_market_data", action="QUOTE", ticker=cfg["code"]),
                timeout=_COLLECT_TIMEOUT,
            )
            if isinstance(result, dict) and result.get("status") == "success":
                data = result.get("data", result)
                return IndexSnapshot(
                    name=cfg["name"],
                    code=cfg["code"],
                    close=float(data.get("last_price", data.get("close", 0))),
                    change_pct=float(data.get("change_pct", data.get("pct_change", 0))),
                    volume=_safe_float(data.get("turnover", data.get("volume"))),
                )
        except Exception as e:
            print(f"⚠️ [MRKT] 指数 {cfg['name']} 采集失败: {e}")
        return None

    tasks = [_fetch_one(cfg) for cfg in indices_cfg]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, IndexSnapshot)]


async def _collect_capital_flow(registry: ToolRegistry, market: MarketType) -> Optional[CapitalFlow]:
    """采集资金流向数据"""
    try:
        # 使用核心 ETF 代表市场资金方向
        etf_map = {
            MarketType.A_SHARE: "SH.510300",  # 沪深300ETF
            MarketType.HK: "HK.02800",  # 盈富基金
            MarketType.US: "US.SPY",  # 标普500ETF
        }
        ticker = etf_map.get(market)
        if not ticker:
            return None

        result = await asyncio.wait_for(
            registry.execute("get_broker_market_data", action="FUND_FLOW", ticker=ticker),
            timeout=_COLLECT_TIMEOUT,
        )
        if isinstance(result, dict) and result.get("status") == "success":
            data = result.get("data", result)
            main_net = _safe_float(data.get("main_fund_net_inflow"))
            # 转换为亿
            main_net_yi = round(main_net / 1e8, 2) if main_net else None
            return CapitalFlow(
                main_net_inflow=main_net_yi,
                conclusion="",  # 由 LLM 填充
            )
    except Exception as e:
        print(f"⚠️ [MRKT] 资金流采集失败: {e}")
    return None


async def _collect_macro_news(registry: ToolRegistry, limit: int = 30) -> list[dict[str, Any]]:
    """采集宏观新闻"""
    try:
        result = await asyncio.wait_for(
            registry.execute("get_macro_news", limit=limit),
            timeout=_COLLECT_TIMEOUT,
        )
        if isinstance(result, dict) and result.get("status") == "success":
            return result.get("data", [])
    except Exception as e:
        print(f"⚠️ [MRKT] 新闻采集失败: {e}")
    return []


async def _collect_sentiment(registry: ToolRegistry) -> Optional[dict[str, Any]]:
    """采集市场情绪指标 (VIX / P/C Ratio)"""
    try:
        result = await asyncio.wait_for(
            registry.execute("get_macro_sentiment_history", days=5),
            timeout=_COLLECT_TIMEOUT,
        )
        if isinstance(result, dict) and result.get("status") == "success":
            return result.get("data", {})
    except Exception as e:
        print(f"⚠️ [MRKT] 情绪数据采集失败: {e}")
    return None


async def _collect_sectors(
    registry: ToolRegistry, market: MarketType
) -> tuple[list[SectorPerformance], list[SectorPerformance]]:
    """并行采集板块涨跌（以行业 ETF 行情作代理），返回 (领涨板块, 领跌板块) 各至多 5 个。"""
    etfs = _SECTOR_ETFS.get(market, [])
    if not etfs:
        return [], []

    async def _fetch_one(cfg: dict[str, str]) -> Optional[SectorPerformance]:
        try:
            result = await asyncio.wait_for(
                registry.execute("get_broker_market_data", action="QUOTE", ticker=cfg["code"]),
                timeout=_COLLECT_TIMEOUT,
            )
            if isinstance(result, dict) and result.get("status") == "success":
                data = result.get("data", result)
                change_pct = float(data.get("change_pct", data.get("pct_change", 0)) or 0)
                return SectorPerformance(
                    name=cfg["name"],
                    change_pct=round(change_pct, 2),
                    net_inflow=None,
                    leading_stock=None,
                    direction="涨" if change_pct >= 0 else "跌",
                )
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ [MRKT] 板块 {cfg['name']} 采集失败: {e}")
        return None

    results = await asyncio.gather(*[_fetch_one(c) for c in etfs], return_exceptions=True)
    valid = [r for r in results if isinstance(r, SectorPerformance)]
    if not valid:
        return [], []
    gainers = sorted((s for s in valid if s.change_pct >= 0), key=lambda s: s.change_pct, reverse=True)
    losers = sorted((s for s in valid if s.change_pct < 0), key=lambda s: s.change_pct)
    top = gainers[:5]
    bottom = losers[:5]
    return top, bottom


# ── LLM 分析 ────────────────────────────────────────────────────────────────
_ANALYSIS_SYSTEM_PROMPT = """你是一位资深量化宏观分析师，负责每日收盘后的市场复盘。
你的任务是基于提供的原始数据（指数行情、资金流向、新闻、情绪指标），生成结构化的市场复盘分析。

要求：
1. 风格判定必须基于数据（大盘vs小盘、价值vs成长、防御vs进攻）
2. 情绪评分 0-100，严格基于 VIX/P-C/涨跌比等客观指标
3. 总结犀利、直击要害，不要废话
4. 风险标签用于下游个股分析时的判因引用
5. key_events 从新闻中提取最重要的 3-5 条，标注影响方向"""


def _build_analysis_prompt(
    market: MarketType,
    date: str,
    indices: list[IndexSnapshot],
    capital: Optional[CapitalFlow],
    news: list[dict[str, Any]],
    sentiment: Optional[dict[str, Any]],
    sectors_top: Optional[list[SectorPerformance]] = None,
    sectors_bottom: Optional[list[SectorPerformance]] = None,
) -> str:
    """构建 LLM 分析 prompt"""
    parts = [f"## 市场: {market.value} | 日期: {date}\n"]

    # 指数行情
    if indices:
        parts.append("## 指数行情")
        for idx in indices:
            vol_str = f", 成交额: {idx.volume}亿" if idx.volume else ""
            parts.append(f"- {idx.name}({idx.code}): 收盘 {idx.close}, 涨跌 {idx.change_pct}%{vol_str}")

    # 板块涨跌
    if sectors_top or sectors_bottom:
        parts.append("\n## 板块涨跌（行业 ETF 代理）")
        if sectors_top:
            parts.append("- 领涨: " + ", ".join(f"{s.name}({s.change_pct}%)" for s in sectors_top))
        if sectors_bottom:
            parts.append("- 领跌: " + ", ".join(f"{s.name}({s.change_pct}%)" for s in sectors_bottom))

    # 资金面
    if capital and capital.main_net_inflow is not None:
        parts.append(f"\n## 资金面\n- 主力净流入: {capital.main_net_inflow}亿")

    # 情绪指标
    if sentiment:
        parts.append(f"\n## 情绪指标\n{json.dumps(sentiment, ensure_ascii=False, default=str)[:1500]}")

    # 新闻
    if news:
        parts.append("\n## 当日新闻 (摘要)")
        for item in news[:15]:
            headline = item.get("headline", item.get("title", ""))
            summary = item.get("summary", "")[:100]
            parts.append(f"- {headline}: {summary}")

    parts.append("\n请基于以上数据生成结构化复盘分析。")
    return "\n".join(parts)


async def _llm_analyze(
    market: MarketType,
    date: str,
    indices: list[IndexSnapshot],
    capital: Optional[CapitalFlow],
    news: list[dict[str, Any]],
    sentiment: Optional[dict[str, Any]],
    sectors_top: Optional[list[SectorPerformance]] = None,
    sectors_bottom: Optional[list[SectorPerformance]] = None,
) -> Optional[_LLMReviewAnalysis]:
    """调用 LLM 生成结构化分析"""
    prompt = _build_analysis_prompt(market, date, indices, capital, news, sentiment, sectors_top, sectors_bottom)
    try:
        analysis = await llm_service.generate_pydantic(
            prompt=prompt,
            response_model=_LLMReviewAnalysis,
            system_prompt=_ANALYSIS_SYSTEM_PROMPT,
            tier=ModelTier.STANDARD,
            temperature=0.3,
        )
        return analysis
    except Exception as e:
        print(f"⚠️ [MRKT] LLM 分析失败: {e}\n{traceback.format_exc()}")
        return None


# ── 主入口 ──────────────────────────────────────────────────────────────────
async def generate_market_review(
    market: MarketType,
    date: Optional[str] = None,
    tool_registry: Optional[ToolRegistry] = None,
) -> MarketDailyReview:
    """
    生成指定市场的每日复盘报告。

    Args:
        market: 市场类型 (A股/港股/美股)
        date: 复盘日期 YYYY-MM-DD，默认今天
        tool_registry: ToolRegistry 实例，默认新建

    Returns:
        MarketDailyReview 完整复盘报告（已持久化到 Redis）
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    registry = tool_registry or ToolRegistry()

    # ── Phase 1: 并行数据采集 ──
    indices_task = _collect_index_quotes(registry, market)
    capital_task = _collect_capital_flow(registry, market)
    news_task = _collect_macro_news(registry)
    sentiment_task = _collect_sentiment(registry)
    sectors_task = _collect_sectors(registry, market)

    indices, capital, news, sentiment, sectors = await asyncio.gather(
        indices_task,
        capital_task,
        news_task,
        sentiment_task,
        sectors_task,
        return_exceptions=False,
    )
    sectors_top, sectors_bottom = sectors if sectors else ([], [])

    # ── Phase 2: LLM 结构化分析 ──
    analysis = await _llm_analyze(market, date, indices, capital, news, sentiment, sectors_top, sectors_bottom)

    # ── Phase 3: 组装 MarketDailyReview ──
    review = MarketDailyReview(
        date=date,
        market=market,
        indices=indices,
        capital_flow=capital,
        sectors_top=sectors_top,
        sectors_bottom=sectors_bottom,
    )

    if analysis:
        # 风格
        review.style = _parse_style(analysis.style)
        review.style_reasoning = analysis.style_reasoning

        # 资金面结论
        if capital:
            capital.conclusion = analysis.capital_conclusion

        # 情绪
        review.sentiment_score = analysis.sentiment_score
        review.sentiment_level = _parse_sentiment_level(analysis.sentiment_level)

        # 事件
        review.event_impact_summary = analysis.event_impact_summary
        review.key_events = _parse_events(analysis.key_events)

        # AI 总结
        review.summary = analysis.summary
        review.outlook = analysis.outlook
        review.risk_tags = analysis.risk_tags

    # ── Phase 4: 持久化 ──
    await save_market_review(review)
    print(f"✅ [MRKT] {market.value} {date} 复盘已生成并存储")

    return review


# ── 辅助函数 ────────────────────────────────────────────────────────────────
def _safe_float(val: Any) -> Optional[float]:
    """安全转换浮点数"""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_style(raw: str) -> Optional[MarketStyle]:
    """解析市场风格枚举"""
    for s in MarketStyle:
        if s.value in raw:
            return s
    return MarketStyle.BALANCED


def _parse_sentiment_level(raw: str) -> Optional[SentimentLevel]:
    """解析情绪等级枚举"""
    for s in SentimentLevel:
        if s.value in raw:
            return s
    return SentimentLevel.NEUTRAL


def _parse_events(raw_events: list[dict[str, Any]]) -> list[MarketEvent]:
    """解析 LLM 输出的事件列表"""
    events = []
    for item in raw_events[:5]:
        try:
            events.append(
                MarketEvent(
                    title=item.get("title", "未知事件"),
                    category=item.get("category", "宏观"),
                    impact=item.get("impact", "中性"),
                    affected_sectors=item.get("affected_sectors", []),
                )
            )
        except Exception:
            continue
    return events
