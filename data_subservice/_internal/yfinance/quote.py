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
        df = yf.download(
            yf_code,
            period=period,
            start=start,
            end=end,
            interval=interval,
            progress=False,
            auto_adjust=True,
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
