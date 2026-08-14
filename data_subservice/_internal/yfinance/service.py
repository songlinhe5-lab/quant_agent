"""
YFinanceService — 雅虎财经数据源实现（物理解耦裁剪版）

复制自 backend.services.yfinance.service，按子服务职责裁剪：
- 移除 YFinanceRouter（主服务多节点出口，子服务是叶子数据源节点，不走 router）
- 移除 backend.services.ai_narrator / alert（仅 MacroDaemon 收盘点评推送用，子服务不跑守护进程）
- 移除 backend.core.middleware 的 Prometheus 出向指标（子服务不上报主集群）
- 移除 finnhub 兜底依赖；子服务 yfinance 自身即数据源
- 保留：quote/flow/hist/search/technical/financials/option_chain 全部核心 fetch 能力
"""

import asyncio
from typing import Any, Dict, List, Optional

import pandas as pd

from data_subservice._internal.circuit_breaker import circuit_breaker
from data_subservice._internal.logger import logger
from data_subservice._internal.yfinance.quote import (
    fetch_bulk_quotes,
    fetch_financials,
    fetch_fund_flow,
    fetch_history,
    fetch_news,
    fetch_option_chain,
    fetch_quote,
)
from data_subservice._internal.yfinance.search import search_tickers
from data_subservice._internal.yfinance.technical import (
    calculate_technical_indicators,
    detect_signals,
)
from data_subservice._internal.yfinance.utils import format_yf_ticker, resolve_date_range


class YFinanceService:
    """
    雅虎财经统一数据源。

    子服务场景：作为叶子数据源节点，直接调用 yfinance 拉取行情/财务/期权，
    不再经过主服务的多节点 Router 与宏观守护进程。
    """

    def __init__(self):
        self._router_enabled = False  # 子服务恒为叶子节点，无 router
        self.source_name = "yfinance"
        # DIST-SEC-01(2026-08-13): 并发信号量，限制同时进行的 yfinance 外部 IO 调用数。
        # 此前无限制并发入站（主服务经 router 批量派发 HISTORY/批量行情）导致 yf.download
        # 内部线程无上限累积、进程线程耗尽、子服务历史数据源瘫痪。
        # 经 .env 的 YF_MAX_CONCURRENCY 可调，默认 8；threads=False 已在 quote.py 关闭 yf 内置线程。
        import os as _os

        _max_conc = int(_os.getenv("YF_MAX_CONCURRENCY", "8"))
        self._yf_semaphore = asyncio.Semaphore(_max_conc)
        logger.info(f"✅ YFinanceService (subservice) 初始化完成 (YF_MAX_CONCURRENCY={_max_conc})")

    # ── 内部工具 ──
    def _ensure_router(self):
        """子服务无 router，no-op。"""
        return None

    def _record_success(self, symbol: str):
        circuit_breaker.record_success(symbol)

    def _record_failure(self, symbol: str, is_rate_limit: bool = False):
        circuit_breaker.record_failure(symbol, is_rate_limit=is_rate_limit)

    @staticmethod
    def _is_data_unavailable(exc: Exception) -> bool:
        """判断异常是否为『数据层面不可用』而非源/传输故障。

        DIST-SEC-04(2026-08-14): yfinance 对部分 ticker（如 $VIX/$IXIC/$SPX 指数、停牌股）
        会抛 'Yahoo error = "No data"' / 'No data found'。这类属于『该标的 Yahoo 无数据』，
        不是子服务故障，绝不能计入熔断（否则单标的 miss 会误杀整节点，连带正常标的也 No healthy node）。
        """
        msg = str(exc).lower()
        markers = ("no data", "yahoo error", "not found", "delisted", "empty dataset", "no data found")
        return any(m in msg for m in markers)

    async def _run_guarded(self, key: str, fn):
        """经并发信号量包裹的 circuit_breaker 调用。

        DIST-SEC-01(2026-08-13): 所有产生 yfinance 外部 IO（yf.download / 爬虫 / API）
        的方法都必须经此入口，确保同时进行的调用数不超过 YF_MAX_CONCURRENCY，
        从根源上防止线程/连接无上限累积导致子服务资源耗尽。
        """
        async with self._yf_semaphore:
            return await circuit_breaker.call(key, fn)

    def get_macro_daemon(self):
        """子服务不运行宏观守护进程，返回 None。"""
        return None

    # ── 统一核心入口 ──
    async def fetch_yf_data(
        self,
        endpoint: str,
        symbol: str,
        **kwargs,
    ) -> Any:
        """统一核心入口，根据 endpoint 路由到具体 fetch 实现。"""
        endpoint = endpoint.lower()

        # 路由表
        if endpoint == "quote":
            return await self.get_quote(symbol)
        elif endpoint == "history":
            return await self.get_history(symbol, **kwargs)
        elif endpoint == "flow":
            return await self.get_fund_flow(symbol)
        elif endpoint == "financials":
            return await self.get_financials(symbol, **kwargs)
        elif endpoint == "option_chain":
            return await self.get_option_chain(symbol, **kwargs)
        elif endpoint == "search":
            return await self.search(symbol, **kwargs)
        elif endpoint == "technical":
            return await self.get_tech_indicators(symbol, **kwargs)
        else:
            logger.warning(f"[YFinance] 未知 endpoint: {endpoint}")
            return {"symbol": symbol, "error": f"unknown endpoint: {endpoint}"}

    # ── 行情快照 ──
    async def get_quote(self, symbol: str, use_cache: bool = True) -> Dict[str, Any]:
        async def _call():
            return await asyncio.to_thread(fetch_quote, symbol)

        try:
            result = await self._run_guarded(f"yfinance:{symbol}", _call)
            self._record_success(symbol)
            return result
        except Exception as e:
            data_unavail = self._is_data_unavailable(e)
            self._record_failure(symbol, is_rate_limit="rate" in str(e).lower())
            logger.error(f"❌ [YFinance] 获取 {symbol} 行情失败: {e}")
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "yfinance",
                "error_category": "data_unavailable" if data_unavail else "source_error",
            }

    # ── 历史 K 线 ──
    async def get_history(
        self,
        symbol: str,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1d",
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        async def _call():
            r_period, r_start, r_end = resolve_date_range(period, start, end)
            df = await asyncio.to_thread(
                fetch_history, symbol, period=r_period, start=r_start, end=r_end, interval=interval
            )
            return self._df_to_records(df)

        try:
            records = await self._run_guarded(f"yfinance:{symbol}", _call)
            self._record_success(symbol)
            return {
                "symbol": symbol,
                "interval": interval,
                "count": len(records) if records else 0,
                "data": records,
                "source": "yfinance",
            }
        except Exception as e:
            data_unavail = self._is_data_unavailable(e)
            self._record_failure(symbol, is_rate_limit="rate" in str(e).lower())
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "yfinance",
                "error_category": "data_unavailable" if data_unavail else "source_error",
            }

    def _df_to_records(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []
        # columns 可能在极少数情况下仍为 MultiIndex, 这里兜底拍平, 与 quote.fetch_history 保持一致
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        records = []
        for _, row in df.iterrows():
            try:

                def _safe_num(key):
                    v = row[key] if key in df.columns else None
                    return float(v) if pd.notna(v) else None

                rec = {
                    "date": str(row["Date"]) if "Date" in df.columns else None,
                    "open": _safe_num("Open"),
                    "high": _safe_num("High"),
                    "low": _safe_num("Low"),
                    "close": _safe_num("Close"),
                    "volume": int(row["Volume"]) if ("Volume" in df.columns and pd.notna(row.get("Volume"))) else 0,
                }
                records.append(rec)
            except Exception:
                continue
        return records

    # ── 资金流向 ──
    async def get_fund_flow(self, symbol: str) -> Dict[str, Any]:
        async def _call():
            return await asyncio.to_thread(fetch_fund_flow, symbol)

        try:
            result = await self._run_guarded(f"yfinance:{symbol}", _call)
            self._record_success(symbol)
            return result
        except Exception as e:
            data_unavail = self._is_data_unavailable(e)
            self._record_failure(symbol)
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "yfinance",
                "error_category": "data_unavailable" if data_unavail else "source_error",
            }

    # ── 期权链 ──
    async def get_option_chain(self, symbol: str, expiration: Optional[str] = None) -> Dict[str, Any]:
        async def _call():
            return await asyncio.to_thread(fetch_option_chain, symbol)

        try:
            result = await self._run_guarded(f"yfinance:{symbol}", _call)
            self._record_success(symbol)
            return result
        except Exception as e:
            data_unavail = self._is_data_unavailable(e)
            self._record_failure(symbol)
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "yfinance",
                "error_category": "data_unavailable" if data_unavail else "source_error",
            }

    # ── 财务数据 ──
    async def get_financials(self, symbol: str, kind: str = "annual") -> Dict[str, Any]:
        async def _call():
            return await asyncio.to_thread(fetch_financials, symbol, kind=kind)

        try:
            result = await self._run_guarded(f"yfinance:{symbol}", _call)
            self._record_success(symbol)
            return result
        except Exception as e:
            data_unavail = self._is_data_unavailable(e)
            self._record_failure(symbol)
            return {
                "symbol": symbol,
                "error": str(e),
                "source": "yfinance",
                "error_category": "data_unavailable" if data_unavail else "source_error",
            }

    # ── 搜索 ──
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        async def _call():
            return await asyncio.to_thread(search_tickers, query, limit=limit)

        try:
            result = await self._run_guarded("yfinance:search", _call)
            self._record_success("search")
            return result
        except Exception as e:
            logger.warning(f"[YF] 搜索失败: {e}")
            self._record_failure("search")
            return []

    # ── 技术指标 ──
    async def get_tech_indicators(
        self,
        symbol: str,
        period: str = "1y",
        indicators: List[str] = None,
    ) -> Dict[str, Any]:
        try:
            yf_code = format_yf_ticker(symbol)
            period, start, end = resolve_date_range(period=period)
            # DIST-SEC-01(2026-08-13): 经信号量约束 yf.download 并发（与 get_history 一致）
            async with self._yf_semaphore:
                df = await asyncio.to_thread(fetch_history, yf_code, period=period)
            if df is None or df.empty:
                return {"symbol": symbol, "error": "no history data", "source": "yfinance"}

            indicators_result = calculate_technical_indicators(df, indicators)
            signals = detect_signals(df)
            return {
                "symbol": symbol,
                "period": period,
                "indicators": indicators_result,
                "signals": signals,
                "source": "yfinance",
            }
        except Exception as e:
            logger.error(f"❌ [YFinance] 计算 {symbol} 技术指标失败: {e}")
            return {"symbol": symbol, "error": str(e), "source": "yfinance"}

    # ── 批量行情（子服务内部调用）──
    async def get_batched_quote(self, tickers: List[str]) -> List[Dict[str, Any]]:
        async def _call():
            return await asyncio.to_thread(fetch_bulk_quotes, tickers)

        try:
            result = await self._run_guarded("yfinance:batch", _call)
            self._record_success("batch")
            return result
        except Exception as e:
            self._record_failure("batch")
            logger.error(f"❌ [YFinance] 批量行情失败: {e}")
            return []

    # ── 新闻（主服务 yahoo_news 兜底远程代理）──
    async def get_news(self, symbol: str, limit: int = 15) -> List[Dict[str, Any]]:
        async def _call():
            return await asyncio.to_thread(fetch_news, symbol, limit=limit)

        try:
            result = await self._run_guarded(f"yfinance:news:{symbol}", _call)
            self._record_success(symbol)
            return result
        except Exception as e:
            self._record_failure(symbol)
            logger.error(f"❌ [YFinance] 获取 {symbol} 新闻失败: {e}")
            return []


# 全局单例
yfinance_service = YFinanceService()
