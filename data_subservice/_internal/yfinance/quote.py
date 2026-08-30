"""YFinance 行情获取（复制自 backend.services.yfinance.quote，物理解耦，零 backend 依赖，相对 import）"""

import math
from typing import Any, Dict, List, Optional

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
            # yfinance 1.x 对单标的返回的 columns 为 MultiIndex, 形如 ('Close','^VIX')。
            # 若不拍平, 下游 _df_to_records 用 row["Close"] 访问会错位/抛异常导致整行被静默丢弃
            # (表现为 count=0 空数据, 但实际有数据)。这里统一拍平为第一级列名。
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        # DIST-SEC-05(2026-08-14): 直接向上抛出，而非吞异常返回空 DF。
        # 雅虎在限流/服务熔断时常把异常伪装成 "possibly delisted" / 返回 None。
        # 旧逻辑吞掉异常返回空 DF -> service 判空 -> count=0 成功返回，主服务 failover
        # 与退避永远触发不了，雅虎熔断期仍高频重试打爆上游。
        # 抛出后由 service._run_guarded 捕获并按 _is_data_unavailable 分类
        # (delisted/No data -> DATA_UNAVAILABLE；网络/连接/限流 -> 源级故障)，
        # 主服务据此 failover 到备份节点 + 退避冷却。
        logger.error(f"[History] 获取 {ticker} 历史失败: {e}")
        raise


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


def _normalize_option_row(row: "pd.Series", option_type: str, expiration: Optional[str] = None) -> Dict:
    """将 yfinance 期权合约一行归一化为后端期望的蛇形字段。"""

    def _num(v: Any) -> Optional[float]:
        try:
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "expiration": expiration,
        "strike": _num(row.get("strike")),
        "option_type": option_type.upper(),
        "bid": _num(row.get("bid")),
        "ask": _num(row.get("ask")),
        "last_price": _num(row.get("lastPrice")),
        "volume": _num(row.get("volume")),
        "open_interest": _num(row.get("openInterest")),
        # yfinance 原始字段为 impliedVolatility(驼峰)；主服务 _enrich_option_chain
        # 读取 implied_volatility，此处统一归一化，避免字段名不匹配导致 IV 全空。
        "implied_volatility": _num(row.get("impliedVolatility")),
    }


def fetch_option_chain(ticker: str) -> Dict:
    """获取期权链（含每个到期日的合约明细与 IV/定价字段）。

    注意：t.option_chain() 返回 OptionsChain 对象，.calls/.puts 为 DataFrame。
    之前实现只取了 list(chain)（到期日列表），丢掉了全部合约数据，
    导致主服务拿不到 IV/定价字段，期权 IV 面板全空。
    """
    import pandas as pd  # row 类型标注 + 下方 isinstance 校验用

    yf_code = format_yf_ticker(ticker)
    try:
        t = yf.Ticker(yf_code)
        chain = t.option_chain()
        if chain is None:
            return {
                "symbol": ticker,
                "expirations": [],
                "calls": [],
                "puts": [],
                "options": [],
                "count": 0,
                "source": "yfinance",
            }
        expirations = list(chain)

        calls: List[Dict] = []
        puts: List[Dict] = []
        for exp in expirations:
            # ⚠️ 无期权链标的（港股 / 无期权品种）yfinance 的 chain.calls/.puts
            # 可能为 None。旧代码在 except 兜底后直接 iterrows() →
            # 'NoneType' object has no attribute 'iterrows' → 被主服务判为
            # 「源级失败」计入 throttler，累积后触发 yfinance 全节点 300s 退避
            # （2026-08-30 S1 实战：0772.HK 触发，consecutive=15 / wait=300.4s），
            # 连累所有走 yfinance 的请求，表现为工具长时间无响应。
            for raw, kind in ((chain.calls, "CALL"), (chain.puts, "PUT")):
                if not isinstance(raw, pd.DataFrame) or raw.empty:
                    continue
                try:
                    df_ = raw[raw["expirationDate"] == exp] if "expirationDate" in raw.columns else raw
                except Exception:  # noqa: BLE001 - 列缺失/类型异常时回退整表
                    df_ = raw
                bucket = calls if kind == "CALL" else puts
                for _, r in df_.iterrows():
                    bucket.append(_normalize_option_row(r, kind, exp))

        all_opts = calls + puts
        return {
            "symbol": ticker,
            "expirations": expirations,
            "calls": calls,
            "puts": puts,
            "options": all_opts,
            "count": len(all_opts),
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
