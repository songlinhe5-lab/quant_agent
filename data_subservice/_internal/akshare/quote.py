"""AKShare 行情获取（复制自 backend.services.akshare.quote，物理解耦，零 backend 依赖，相对 import）"""

from typing import Any, Dict, List, Optional

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


def _build_sina_symbol(code: str) -> str:
    """将 6 位 A 股代码转为新浪接口所需前缀格式 (sh/sz)。

    上交所: 60/68/9 开头 → sh；深交所: 00/30 开头 → sz。
    """
    code = code.zfill(6)
    if code.startswith(("60", "68", "90", "88")):
        return f"sh{code}"
    return f"sz{code}"


def _parse_company_news(ticker: str) -> Dict[str, Any]:
    """个股新闻解析（A 股东方财富 stock_news_em），返回与主服务一致的 {status,data,source} 结构。

    港股新闻降级交由主服务走 yahoo，这里遇港股代码直接返回空成功。
    """
    import re
    from datetime import datetime, timezone

    upper = ticker.upper()
    if "HK" in upper or (ticker.isdigit() and len(ticker) == 5):
        return {"status": "success", "data": [], "source": "akshare_empty_hk"}
    if "BK" in upper:
        return {
            "status": "warning",
            "message": f"[{ticker}] 为板块指数，不适用个股新闻接口",
            "data": [],
        }

    match = re.search(r"\d+", ticker)
    if not match:
        raise ValueError(f"无法从代码 {ticker} 提取纯数字代码以获取新闻")
    symbol = match.group()
    if "SH" in upper or "SZ" in upper:
        symbol = symbol.zfill(6)

    df = ak.stock_news_em(symbol=symbol)
    if df is None or df.empty:
        raise ValueError(f"获取到的 {ticker} 新闻数据为空")

    if "发布时间" in df.columns:
        df = df.sort_values(by="发布时间", ascending=False)

    news_list = []
    for _, row in df.head(30).iterrows():
        pub_time = str(row.get("发布时间", ""))
        try:
            dt = datetime.strptime(pub_time, "%Y-%m-%d %H:%M:%S")
            ts = dt.replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            ts = datetime.now().timestamp()
        news_list.append(
            {
                "datetime": ts,
                "date": pub_time,
                "headline": str(row.get("新闻标题", "")),
                "summary": str(row.get("新闻内容", "")),
                "url": str(row.get("新闻链接", "")),
                "source": str(row.get("文章来源", "东方财富")),
            }
        )
    return {"status": "success", "data": news_list, "source": "akshare"}


@with_global_retry
def get_company_news(ticker: str) -> Dict[str, Any]:
    """个股新闻（A 股）。港股由主服务降级 yahoo，本端仅返回空成功。"""
    try:
        return _parse_company_news(ticker)
    except Exception as e:
        logger.error(f"[AKShare] 个股新闻 {ticker} 失败: {e}")
        return {"status": "error", "message": f"AKShare 个股新闻获取失败: {e}", "data": []}


@with_global_retry
def get_stock_quote_a_sina(ticker: str) -> Dict[str, Any]:
    """A 股实时行情兜底（新浪源），返回与主服务 get_stock_quote 一致的结构。"""
    import re
    from datetime import datetime, timezone

    match = re.search(r"\d+", ticker)
    if not match:
        return {"status": "error", "message": "无效的 A 股代码", "data": None}
    symbol = match.group().zfill(6)
    try:
        if hasattr(ak, "set_proxy"):
            ak.set_proxy(None)
        sina_symbol = _build_sina_symbol(symbol)
        df = ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq")
        if df is None or df.empty:
            raise ValueError("获取到的个股行情为空")
        latest = df.iloc[-1]
        prev_close = float(df.iloc[-2]["close"]) if len(df) > 1 else float(latest["open"])
        last_price = float(latest["close"])
        change = last_price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close > 0 else 0.0
        vol = float(latest["volume"])
        high = float(latest["high"])
        low = float(latest["low"])
        amplitude = ((high - low) / prev_close * 100) if prev_close > 0 else 0.0
        data = {
            "ticker": ticker,
            "last_price": last_price,
            "open": float(latest["open"]),
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": vol,
            "turnover": float(latest["amount"]),
            "change_val": change,
            "change_pct": change_pct,
            "amplitude": amplitude,
            "volume_str": f"{vol / 1_000_000:.2f}M" if vol > 1_000_000 else f"{vol / 1_000:.2f}K",
        }
        return {
            "status": "success",
            "data": data,
            "source": "akshare_sina",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"[AKShare] A 股行情 {ticker} 失败: {e}")
        return {"status": "error", "message": f"行情异常: {e}", "data": None}


@with_global_retry
def get_stock_history_a_sina(ticker: str, num: int = 60) -> Dict[str, Any]:
    """A 股历史 K 线兜底（新浪源），返回与主服务 get_stock_history 一致的结构。"""
    import re

    match = re.search(r"\d+", ticker)
    if not match:
        return {"status": "error", "message": "无效的 A 股代码", "data": None}
    symbol = match.group().zfill(6)
    try:
        if hasattr(ak, "set_proxy"):
            ak.set_proxy(None)
        sina_symbol = _build_sina_symbol(symbol)
        df = ak.stock_zh_a_daily(symbol=sina_symbol, adjust="qfq")
        if df is None or df.empty:
            raise ValueError("获取到的 K 线为空")
        df = df.tail(num)
        data_list = [
            {
                "time": str(row["date"]) + " 00:00:00",
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            for _, row in df.iterrows()
        ]
        return {"status": "success", "data": data_list, "source": "akshare_fallback"}
    except Exception as e:
        logger.error(f"[AKShare] A 股历史 {ticker} 失败: {e}")
        return {"status": "error", "message": f"K线异常: {e}", "data": None}
