"""AKShare 行情获取（复制自 backend.services.akshare.quote，物理解耦，零 backend 依赖，相对 import）"""

from typing import Dict, List, Optional

import akshare as ak
import pandas as pd

from data_subservice._internal.logger import logger
from data_subservice._internal.retry_utils import with_global_retry


@with_global_retry
def get_spot_a_quote(symbol: str) -> Optional[Dict]:
    """获取 A 股实时行情快照。"""
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "symbol": symbol,
            "name": r.get("名称"),
            "price": float(r["最新价"]),
            "change_pct": float(r["涨跌幅"]),
            "volume": int(r["成交量"]),
            "turnover": float(r["成交额"]),
            "source": "akshare",
        }
    except Exception as e:
        logger.error(f"[AKShare] A股行情 {symbol} 失败: {e}")
        return None


@with_global_retry
def get_us_stock_quote(symbol: str) -> Optional[Dict]:
    """获取美股实时行情快照。"""
    try:
        df = ak.stock_us_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "symbol": symbol,
            "name": r.get("名称"),
            "price": float(r["最新价"]),
            "change_pct": float(r["涨跌幅"]),
            "source": "akshare",
        }
    except Exception as e:
        logger.error(f"[AKShare] 美股行情 {symbol} 失败: {e}")
        return None


@with_global_retry
def get_hk_stock_quote(symbol: str) -> Optional[Dict]:
    """获取港股实时行情快照。"""
    try:
        df = ak.stock_hk_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "symbol": symbol,
            "name": r.get("名称"),
            "price": float(r["最新价"]),
            "change_pct": float(r["涨跌幅"]),
            "source": "akshare",
        }
    except Exception as e:
        logger.error(f"[AKShare] 港股行情 {symbol} 失败: {e}")
        return None


@with_global_retry
def get_history(symbol: str, market: str = "A", period: str = "daily") -> pd.DataFrame:
    """获取历史 K 线。"""
    try:
        if market == "A":
            df = ak.stock_zh_a_hist(symbol=symbol, period=period, adjust="qfq")
        elif market == "HK":
            df = ak.stock_hk_hist(symbol=symbol, period=period, adjust="qfq")
        elif market == "US":
            df = ak.stock_us_hist(symbol=symbol, period=period, adjust="qfq")
        else:
            df = pd.DataFrame()
        return df
    except Exception as e:
        logger.error(f"[AKShare] 历史 {symbol} 失败: {e}")
        return pd.DataFrame()


@with_global_retry
def get_hk_news(days: int = 3) -> List[Dict]:
    """获取港股新闻（子服务内 finnhub 兜底已降级为直接返回空，由 yfinance 单独调用补充）。"""
    try:
        df = ak.stock_news_em(symbol="港股")
        if df is None or df.empty:
            return []
        df = df.head(days * 5)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.warning(f"[AKShare] 港股新闻获取失败: {e}")
        return []
