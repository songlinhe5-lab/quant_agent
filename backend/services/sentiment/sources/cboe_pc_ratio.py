"""
P/C Ratio（Put/Call Ratio）—— CBOE 官方每日市场统计公开源

数据来源 (CBOE 官方公开披露，免 token、无反爬、主站 HTML 直取)：
- 每日统计页：https://www.cboe.com/markets/us/options/market-statistics/daily
- 页面内 Next.js 流式注入的结构化 JSON 含 optionsData.ratios 数组，
  形如 [{"name":"TOTAL PUT/CALL RATIO","value":"0.84"}, ...]，
  覆盖 TOTAL / INDEX / EQUITY / EXCHANGE TRADED PRODUCTS 等细分 P/C。

为什么不用 yfinance `^CPC`：
- yfinance 在 Yahoo 上根本没有 `^CPC` 这个 ticker（实测 Quote not found / possibly delisted），
  因此原 sentiment_tracker 读取的 `yf_macro_cache_^CPC` 键永远不存在。
- 本项目采用 CBOE 官方页面的 TOTAL PUT/CALL RATIO 作为 P/C 上游，
  写入 `yf_macro_cache_^CPC`（结构对齐 yf_macro_cache_^VIX 的 records 形态：
  [{"date","open","high","low","close","volume"}]），使读侧零改动即可拿到真实 P/C。

设计定位：
- 仅取 TOTAL PUT/CALL RATIO（市场整体情绪最常用口径）。
- 无数据 / 抓取失败返回 None，由 daemon 降级，绝不写假数据（零幻觉红线）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# CBOE 每日期权市场统计页（主站 HTML，非 CDN，GET 200 可直取）
CBOE_DAILY_STATS_URL = "https://www.cboe.com/markets/us/options/market-statistics/daily"

# UA：模拟桌面浏览器，规避简单反爬
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# CBOE 每日统计页把数据以 Next.js __next_f.push 内嵌，且经两层 JSON.stringify 转义，
# 真实字节形如：\\\\"name\\\\":\\\\"TOTAL PUT/CALL RATIO\\\\",\\\\"value\\\\":\\\\"0.84\\\\"
# 故先用 replace 剥掉转义层，再按普通 JSON 形态匹配。
_RATIO_RE = re.compile(
    r'"name"\s*:\s*"TOTAL PUT/CALL RATIO"\s*,\s*"value"\s*:\s*"([0-9]*\.?[0-9]+)"',
    re.IGNORECASE,
)


def _parse_total_pc_ratio(html: str) -> Optional[float]:
    """从 CBOE 每日统计页 HTML 中解析 TOTAL PUT/CALL RATIO。"""
    if not html:
        return None
    # 剥掉 Next.js 双层转义：\\" -> "
    normalized = html.replace('\\"', '"')
    m = _RATIO_RE.search(normalized)
    if not m:
        return None
    try:
        return float(m.group(1))
    except (TypeError, ValueError):
        return None


async def fetch_total_put_call_ratio(http_get=None) -> Optional[float]:
    """抓取并返回 CBOE TOTAL PUT/CALL RATIO。

    Args:
        http_get: 可选注入的异步 GET 函数 (url, headers) -> text，便于单测。
                  默认使用 aiohttp/requests 直连主站。

    Returns:
        P/C 比值（float）或 None（抓取/解析失败）。
    """
    try:
        if http_get is None:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    CBOE_DAILY_STATS_URL,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status != 200:
                        logger.warning("[Sentiment][cboe] P/C 页 HTTP 异常", status=resp.status)
                        return None
                    html = await resp.text()
        else:
            html = await http_get(CBOE_DAILY_STATS_URL, headers={"User-Agent": _USER_AGENT})

        pc = _parse_total_pc_ratio(html)
        if pc is None:
            logger.warning("[Sentiment][cboe] 未能从页面解析出 TOTAL PUT/CALL RATIO")
            return None
        logger.info("[Sentiment][cboe] P/C Ratio 抓取成功", value=pc)
        return pc
    except Exception as exc:  # noqa: BLE001 - 防御性，抓取失败不应中断 daemon
        logger.warning("[Sentiment][cboe] P/C 抓取异常", error=str(exc))
        return None


def build_cache_records(pc_ratio: float, as_of: Optional[datetime] = None) -> str:
    """构造与 yf_macro_cache_^VIX 对齐的 records JSON 字符串。

    records 形态: [{"date","open","high","low","close","volume"}]
    P/C 是比率（非价格），open/high/low/close 统一存同一值，便于读侧取 close。
    """
    as_of = as_of or datetime.now(timezone.utc)
    date_str = as_of.strftime("%Y-%m-%d 00:00:00")
    record = {
        "date": date_str,
        "open": pc_ratio,
        "high": pc_ratio,
        "low": pc_ratio,
        "close": pc_ratio,
        "volume": 0,
    }
    return json.dumps([record], default=str)
