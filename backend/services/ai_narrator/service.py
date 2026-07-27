"""AI-01: 市场指挥中心·异动解说员

数据驱动的异动解说：当标的涨跌幅突破阈值(默认>2%)时，基于真实工具数据
(get_company_news / get_fundamental_data) 让 LLM 归纳出一句话解说，并带来源与置信度。
严格遵循 AGENTS.md 零幻觉原则——解说必须完全基于工具返回的真实字段，禁止编造数字。
"""

import asyncio
import logging
from typing import Optional

from backend.services.ai_narrator.models import NarrativeResult
from backend.services.llm_service import LLMService, ModelTier
from hermes_agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

NARRATOR_TOOLS = ["get_company_news", "get_fundamental_data"]

SYSTEM_PROMPT = (
    "你是 Quant Agent 主脑的异动解说员。你只能基于【真实数据】中用方括号标注的"
    "新闻标题与基本面字段，归纳出一句不超过 40 字的中文一句话解说，毒舌、硬核、"
    "带金融黑话，且必须明确说出数据来源(如'据最新公司新闻'/'据基本面')。"
    "若【真实数据】含【形态历史胜率】，须在点评中带出该胜率并据此给出方向倾向。"
    "严禁使用任何【真实数据】以外的信息，严禁编造任何数字。若【真实数据】为空，"
    "直接回复：暂无可信数据源，拒绝在真空里解说。"
)

NARRATE_PROMPT = """标的 {symbol} 当前{direction}幅 {change_pct}%（异动阈值 {threshold}%），请基于以下【真实数据】给出一句话解说。

=== 真实数据 ===
{data}
"""


class AiNarratorService:
    """异动解说服务：采集真实数据 -> LLM 归纳一句话解说"""

    def __init__(self, llm: Optional[LLMService] = None, tool_registry=None):
        self.llm = llm or LLMService()
        self.tool_registry = tool_registry or ToolRegistry()

    async def narrate(
        self,
        symbol: str,
        change_pct: float,
        direction: str = "up",
        threshold: float = 2.0,
        include_pattern_winrate: bool = False,
        pattern_winrate: Optional[float] = None,
        pattern_name: Optional[str] = None,
    ) -> NarrativeResult:
        news, fundamentals = await self._collect(symbol)
        data_bundle = self._format_data(news, fundamentals)
        # 形态历史胜率联动：仅当客户端基于真实 K 线回测出有效胜率时接入，严禁捏造
        if include_pattern_winrate and pattern_winrate is not None:
            name = pattern_name or "当前形态"
            pattern_block = f"【形态历史胜率】{name} 历史回测胜率 {pattern_winrate * 100:.0f}%"
            data_bundle = f"{data_bundle}\n\n{pattern_block}".strip() if data_bundle else pattern_block
        summary, source, confidence = await self._build(
            symbol, change_pct, direction, threshold, data_bundle, has_data=bool(data_bundle)
        )
        return NarrativeResult(
            symbol=symbol,
            direction=direction,
            change_pct=change_pct,
            threshold=threshold,
            summary=summary,
            source=source,
            confidence=confidence,
            triggered_by="price_anomaly",
            pattern_winrate=pattern_winrate if (include_pattern_winrate and pattern_winrate is not None) else None,
        )

    # ─── 数据采集 ──────────────────────────────────────────────
    async def _collect(self, symbol):
        async def safe(name: str, coro):
            try:
                return await coro
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[Narrator] {name} 采集失败: {e}")
                return None

        news_t, fund_t = await asyncio.gather(
            safe("get_company_news", self.tool_registry.execute("get_company_news", ticker=symbol)),
            safe(
                "get_fundamental_data",
                self.tool_registry.execute("get_fundamental_data", ticker=symbol),
            ),
        )
        return news_t, fund_t

    # ─── 数据精简(喂给 LLM, 控 token) ────────────────────────
    def _format_data(self, news, fundamentals) -> str:
        parts: list[str] = []
        if news:
            try:
                nlist = news.get("news") or news.get("data") or news
                if isinstance(nlist, dict):
                    nlist = [nlist]
                lines = [
                    f"- [新闻] {n.get('time') or ''} | {n.get('title')} | {n.get('summary') or ''}" for n in nlist[:5]
                ]
                if lines:
                    parts.append("【公司新闻】\n" + "\n".join(lines))
            except Exception:  # noqa: BLE001
                pass
        if fundamentals:
            try:
                f = fundamentals.get("data") or fundamentals
                if isinstance(f, dict):
                    lines = [
                        f"- [基本面] {k}={f.get(k)}"
                        for k in ("pe", "pb", "roe", "short_ratio", "market_cap", "eps")
                        if f.get(k) is not None
                    ]
                    if lines:
                        parts.append("【基本面】\n" + "\n".join(lines))
            except Exception:  # noqa: BLE001
                pass
        return "\n\n".join(parts)

    # ─── LLM 归纳(失败降级) ───────────────────────────────────
    async def _build(self, symbol, change_pct, direction, threshold, data_bundle, has_data):
        if not has_data:
            return ("暂无可信数据源，拒绝在真空里解说", "无", 0.0)
        prompt = NARRATE_PROMPT.format(
            symbol=symbol,
            direction=direction,
            change_pct=change_pct,
            threshold=threshold,
            data=data_bundle,
        )
        try:
            text = await self.llm.generate(prompt, tier=ModelTier.STANDARD, system_prompt=SYSTEM_PROMPT)
            text = (text or "").strip()
            if len(text) < 5:
                raise ValueError("LLM 返回过短")
            return (text, " / ".join(NARRATOR_TOOLS), 0.7)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Narrator] LLM 归纳失败，降级: {e}")
            snippet = data_bundle[:80].replace("\n", " ")
            return (f"异动 {change_pct}%，相关：{snippet}", "原始数据(未归纳)", 0.4)
