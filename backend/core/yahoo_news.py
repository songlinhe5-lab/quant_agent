"""Yahoo Finance 新闻兜底客户端（远程代理版）。

港股/A股新闻降级路径：当 AKShare / Finnhub 不可用或命中港股正则解析异常时，
经 DataSourceRouter 联邦到 US-YF-A/B 子服务的 yfinance NEWS action 兜底获取新闻。
本模块不再直连 query2.finance.yahoo.com —— Yahoo 流量 100% 外移至 yfinance 子服务，
主服务仅做字段归一化（与 Finnhub 一致的 category/datetime/headline/summary/source/url/related）。
"""

from __future__ import annotations

import time
from typing import List

from backend.services.datasource.router import data_source_router


async def fetch_yahoo_news(symbol: str) -> List[dict]:
    """使用 YFinance 子服务 NEWS action 兜底获取新闻。

    返回与 Finnhub 一致的字段结构：``category/datetime/headline/summary/
    source/url/related``。失败返回空列表。
    """
    try:
        # 归一化为 Yahoo 适用的 Ticker：港股支持「HK.00700」(Futu/AKShare 前缀式)
        # 与「00700.HK」(Yahoo 后缀式) 两种输入，统一转为 4 位代码 + .HK
        yf_ticker = symbol
        if yf_ticker.upper().startswith("HK."):
            code = yf_ticker[3:]
        elif yf_ticker.upper().endswith(".HK"):
            code = yf_ticker[:-3]
        else:
            code = yf_ticker
        if code.isdigit():
            yf_ticker = f"{code.lstrip('0').zfill(4)}.HK"

        remote = await data_source_router.fetch_yfinance("NEWS", yf_ticker, limit=15)
        if remote.get("status") != "success" and not remote.get("success"):
            return []

        raw_news = remote.get("data") or []
        if not isinstance(raw_news, list):
            return []

        formatted_news: List[dict] = []
        for item in raw_news:
            if not isinstance(item, dict):
                continue
            formatted_news.append(
                {
                    "category": "company",
                    "datetime": item.get("provider_publish_time", int(time.time())),
                    "headline": item.get("title", ""),
                    "summary": item.get("publisher", "Yahoo Finance"),
                    "source": item.get("publisher", "Yahoo Finance"),
                    "url": item.get("link", ""),
                    "related": symbol,
                }
            )
        return formatted_news
    except Exception as e:
        print(f"⚠️ [Yahoo Fallback] 兜底获取 {symbol} 新闻失败: {e}")
        return []
