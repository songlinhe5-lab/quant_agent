"""Yahoo Finance 新闻兜底客户端（独立于 FinnhubService）。

港股/A股新闻降级路径：当 AKShare / Finnhub 不可用或命中港股正则解析异常时，
经 Yahoo Finance 非官方搜索接口兜底获取新闻。本模块不依赖 backend 任何
数据源 service，仅使用 httpx 直连 Yahoo，彻底与 FinnhubService 解耦。
"""

from __future__ import annotations

import os
import random
import time
from typing import List

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response

_YAHOO_NEWS_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={ticker}&quotesCount=0&newsCount=15"  # noqa: E501


def _get_proxy() -> str | None:
    """从环境变量获取代理 IP 池并进行随机轮换。"""
    proxy_pool = os.getenv("PROXY_POOL", "")
    if proxy_pool:
        proxies = [p.strip() for p in proxy_pool.split(",") if p.strip()]
        if proxies:
            return random.choice(proxies)
    return None


async def fetch_yahoo_news(symbol: str) -> List[dict]:
    """使用 Yahoo Finance 非官方搜索接口兜底获取新闻。

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

        url = _YAHOO_NEWS_URL.format(ticker=yf_ticker)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"  # noqa: E501
        }
        async with httpx.AsyncClient(
            timeout=10.0,
            verify=False,
            proxy=_get_proxy(),
            event_hooks={
                "request": [httpx_log_request],
                "response": [httpx_log_response],
            },
        ) as client:
            res = await client.get(url, headers=headers)
            res.raise_for_status()
            data = res.json()

            news_list = data.get("news", [])
            formatted_news: List[dict] = []
            for item in news_list:
                # 将 Yahoo 数据格式化为与 Finnhub 完全一致的字段结构
                formatted_news.append(
                    {
                        "category": "company",
                        "datetime": item.get("providerPublishTime", int(time.time())),
                        "headline": item.get("title", ""),
                        "summary": item.get("publisher", "Yahoo Finance"),  # Yahoo搜索通常无长摘要，使用出版方占位
                        "source": item.get("publisher", "Yahoo Finance"),
                        "url": item.get("link", ""),
                        "related": symbol,
                    }
                )
            return formatted_news
    except Exception as e:
        print(f"⚠️ [Yahoo Fallback] 兜底获取 {symbol} 新闻失败: {e}")
        return []
