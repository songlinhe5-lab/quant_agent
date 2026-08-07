"""YFinance 标的搜索（复制自 backend.services.yfinance.search，物理解耦，零 backend 依赖，相对 import）"""

from typing import List

import yfinance as yf

from data_subservice._internal.logger import logger


def search_tickers(query: str, limit: int = 10) -> List[dict]:
    """搜索标的代码与名称。"""
    try:
        results = yf.Tickers(query)
        items = []
        for tk, obj in results.tickers.items():
            try:
                info = obj.fast_info
                items.append(
                    {
                        "symbol": tk,
                        "name": getattr(info, "short_name", None),
                        "currency": getattr(info, "currency", None),
                        "exchange": getattr(info, "exchange", None),
                    }
                )
                if len(items) >= limit:
                    break
            except Exception:
                continue
        return items
    except Exception as e:
        logger.error(f"[Search] 搜索 {query} 失败: {e}")
        return []
