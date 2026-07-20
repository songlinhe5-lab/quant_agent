"""
MRKT-05: 判因上下文注入器

个股分析时自动拉取近3日市场复盘，构建判因链：
  大盘系统性 → 板块资金流 → 个股跟跌/跟涨

集成点: Hermes Agent chat_stream_async 在用户消息含个股标的时自动注入。
"""

from __future__ import annotations

import re
from typing import Optional

from backend.services.market_review.models import MarketType
from backend.services.market_review.storage import get_recent_reviews

# ── 标的 → 市场映射规则 ─────────────────────────────────────────────────────
_HK_PATTERN = re.compile(r"\b\d{4,5}\.HK\b|\bHK\.\d{4,5}\b|\b0\d{4}\b", re.IGNORECASE)
_A_SHARE_PATTERN = re.compile(r"\b\d{6}\.(SH|SZ)\b|\b(SH|SZ)\.\d{6}\b|\b[36]\d{5}\b", re.IGNORECASE)
_US_PATTERN = re.compile(r"\b[A-Z]{1,5}\b(?!\.)")  # 宽松匹配，需结合上下文

# 常见美股标的白名单 (避免误判)
_US_KNOWN = {
    "AAPL",
    "TSLA",
    "MSFT",
    "GOOG",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "AMD",
    "INTC",
    "NFLX",
    "DIS",
    "BA",
    "JPM",
    "GS",
    "MS",
    "V",
    "MA",
    "PYPL",
    "SQ",
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "SOXX",
    "KWEB",
    "PLTR",
    "SOFI",
    "RIVN",
    "LCID",
    "NIO",
    "XPEV",
    "LI",
    "BABA",
    "JD",
    "PDD",
    "BIDU",
    "TME",
    "BILI",
    "ZTO",
    "MOMO",
    "TAL",
    "EDU",
    "FUTU",
    "TIGR",
}

# 港股常见标的 (5位数字)
_HK_KNOWN_PREFIXES = (
    "00",
    "01",
    "02",
    "03",
    "06",
    "07",
    "09",
    "10",
    "11",
    "12",
    "13",
    "14",
    "15",
    "16",
    "17",
    "18",
    "19",
    "20",
    "21",
    "22",
    "23",
    "24",
    "25",
    "26",
    "27",
    "28",
    "33",
    "36",
    "38",
    "39",
    "60",
    "61",
    "66",
    "68",
    "69",
    "96",
    "98",
    "99",
)


def detect_market_from_ticker(ticker: str) -> Optional[MarketType]:
    """从标的代码推断所属市场"""
    ticker_upper = ticker.upper().strip()

    # 明确后缀
    if ".HK" in ticker_upper or ticker_upper.startswith("HK."):
        return MarketType.HK
    if ".SH" in ticker_upper or ".SZ" in ticker_upper or ticker_upper.startswith(("SH.", "SZ.")):
        return MarketType.A_SHARE
    if ".US" in ticker_upper or ticker_upper.startswith("US."):
        return MarketType.US

    # 纯数字推断
    digits = re.sub(r"[^0-9]", "", ticker)
    if len(digits) == 5:
        return MarketType.HK
    if len(digits) == 6:
        return MarketType.A_SHARE

    # 美股白名单
    clean = ticker_upper.replace("US.", "").replace(".US", "")
    if clean in _US_KNOWN:
        return MarketType.US

    return None


def detect_market_from_text(text: str) -> Optional[MarketType]:
    """从用户输入文本中检测是否提及个股标的，推断市场"""
    # 港股: 5位数字或 XXXX.HK
    if _HK_PATTERN.search(text):
        return MarketType.HK

    # A股: 6位数字或 XXXXXX.SH/SZ
    if _A_SHARE_PATTERN.search(text):
        return MarketType.A_SHARE

    # 美股: 大写缩写
    for match in _US_PATTERN.finditer(text):
        word = match.group()
        if word in _US_KNOWN:
            return MarketType.US

    return None


async def build_market_context(market: MarketType, days: int = 3) -> Optional[str]:
    """
    构建判因上下文字符串。

    返回格式化的市场复盘摘要，供注入 Agent 上下文。
    无数据时返回 None。
    """
    reviews = await get_recent_reviews(market, days=days)
    if not reviews:
        return None

    lines = [f"📊 【宏观判因上下文】{market.value} 近{len(reviews)}日市场复盘：\n"]

    for review in reviews:
        lines.append(f"── {review.date} ──")

        # 指数
        if review.indices:
            idx_strs = [f"{i.name} {i.change_pct:+.2f}%" for i in review.indices]
            lines.append(f"  指数: {' | '.join(idx_strs)}")

        # 风格
        if review.style:
            lines.append(f"  风格: {review.style.value} ({review.style_reasoning})")

        # 资金面
        if review.capital_flow and review.capital_flow.conclusion:
            lines.append(f"  资金: {review.capital_flow.conclusion}")

        # 情绪
        if review.sentiment_score is not None:
            lines.append(
                f"  情绪: {review.sentiment_score}/100 ({review.sentiment_level.value if review.sentiment_level else ''})"
            )

        # 风险标签
        if review.risk_tags:
            lines.append(f"  风险标签: {', '.join(review.risk_tags)}")

        # 总结
        if review.summary:
            lines.append(f"  总结: {review.summary}")

        lines.append("")

    lines.append(
        "💡 判因指引: 分析个股时，请先判断其涨跌是否受大盘系统性因素驱动（参考上述风险标签和风格），再归因到板块/个股层面。"
    )

    return "\n".join(lines)


async def try_inject_market_context(user_text: str) -> Optional[str]:
    """
    尝试从用户输入中检测标的并构建判因上下文。

    Returns:
        判因上下文字符串，或 None（未检测到个股标的/无复盘数据）
    """
    market = detect_market_from_text(user_text)
    if not market:
        return None

    return await build_market_context(market, days=3)
