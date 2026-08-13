"""YFinance 行情获取（复制自 backend.services.yfinance.quote，物理解耦，零 backend 依赖，相对 import）"""

from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from data_subservice._internal.logger import logger
from data_subservice._internal.yfinance.utils import (
    format_yf_ticker,
    resolve_date_range,  # noqa: F401
)


def fetch_quote(ticker: str) -> Dict:
    """获取单只标的的实时行情快照。"""
    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        info = t.fast_info

        price = getattr(info, "last_price", None)
        prev_close = getattr(info, "previous_close", None)

        change = None
        change_pct = None
        if price is not None and prev_close is not None and prev_close:
            change = price - prev_close
            change_pct = (change / prev_close) * 100

        return {
            "symbol": ticker,
            "yf_code": yf_code,
            "price": float(price) if price is not None else None,
            "prev_close": float(prev_close) if prev_close is not None else None,
            "change": float(change) if change is not None else None,
            "change_pct": float(change_pct) if change_pct is not None else None,
            "currency": getattr(info, "currency", None),
            "timezone": getattr(info, "timezone", None),
            "source": "yfinance",
        }
    except Exception as e:
        logger.error(f"[Quote] 获取 {ticker} 行情失败: {e}")
        return {"symbol": ticker, "error": str(e), "source": "yfinance"}


def fetch_history(
    ticker: str,
    period: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    interval: str = "1d",
) -> pd.DataFrame:
    """获取历史 K 线数据。"""
    yf_code = format_yf_ticker(ticker)
    try:
        # DIST-SEC-01(2026-08-13): yf.download 默认会为内部数据区间拉取 spawn 多线程。
        # 高频并发入站时（主服务经 router 批量派发 HISTORY）线程无上限累积，
        # 最终打爆进程线程上限 → "can't start new thread" → 子服务历史数据源瘫痪。
        # threads=False 关闭其内置多线程，并发改为由 YFinanceService 的 Semaphore 统一管控。
        df = yf.download(
            yf_code,
            period=period,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=True,
            threads=False,
        )
        if df is not None and not df.empty:
            df = df.reset_index()
        return df
    except Exception as e:
        logger.error(f"[History] 获取 {ticker} 历史失败: {e}")
        return pd.DataFrame()


def fetch_fund_flow(ticker: str) -> Dict:
    """获取主力资金流向。"""
    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        df = t.get_institutional_holders()
        if df is not None and not df.empty:
            holders = df.to_dict(orient="records")
        else:
            holders = []
        return {
            "symbol": ticker,
            "institutional_holders": holders,
            "source": "yfinance",
        }
    except Exception as e:
        logger.error(f"[FundFlow] 获取 {ticker} 资金流失败: {e}")
        return {"symbol": ticker, "error": str(e), "source": "yfinance"}


def fetch_financials(ticker: str, kind: str = "annual") -> Dict:
    """获取基本面财务数据。"""
    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        if kind == "quarterly":
            income = t.quarterly_income_stmt
        else:
            income = t.income_stmt

        if income is not None and not income.empty:
            records = income.head(4).to_dict(orient="records")
        else:
            records = []

        return {
            "symbol": ticker,
            "kind": kind,
            "financials": records,
            "source": "yfinance",
        }
    except Exception as e:
        logger.error(f"[Financials] 获取 {ticker} 财务失败: {e}")
        return {"symbol": ticker, "error": str(e), "source": "yfinance"}


def fetch_option_chain(ticker: str) -> Dict:
    """获取期权链。"""
    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        chain = t.option_chain()
        expirations = list(chain)
        return {
            "symbol": ticker,
            "expirations": expirations,
            "source": "yfinance",
        }
    except Exception as e:
        logger.error(f"[OptionChain] 获取 {ticker} 期权链失败: {e}")
        return {"symbol": ticker, "error": str(e), "source": "yfinance"}


def fetch_bulk_quotes(tickers: List[str]) -> List[Dict]:
    """批量获取行情快照（YFinanceService 内部调用）。"""
    results = []
    for tk in tickers:
        results.append(fetch_quote(tk))
    return results


def fetch_news(ticker: str, limit: int = 15) -> List[Dict]:
    """获取标的 Yahoo 新闻（远程代理主服务 yahoo_news 兜底的底层数据源）。

    yfinance 库经 Yahoo Finance 非官方 news 接口拉取，子服务持有 Yahoo 出口能力，
    主服务不再直连 query2.finance.yahoo.com。
    """
    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        raw = t.news or []
        items = []
        for item in raw[:limit]:
            items.append(
                {
                    "uuid": item.get("uuid"),
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", "Yahoo Finance"),
                    "link": item.get("link", ""),
                    "provider_publish_time": item.get("providerPublishTime"),
                    "type": item.get("type", "STORY"),
                    "related_tickers": item.get("relatedTickers", []),
                }
            )
        return items
    except Exception as e:
        logger.error(f"[News] 获取 {ticker} 新闻失败: {e}")
        return []
