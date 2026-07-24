"""
YFinanceAdapter - Yahoo Finance 数据源适配器

基于 DataSourcePort Protocol 实现的具体数据源 Adapter，负责从 Yahoo Finance 获取
行情、历史 K 线、宏观指标等数据。

主要用途：
- Futu 无法覆盖的标的（美股完整列表、加密货币、外汇）
- Futu 限流或不可用时的降级兜底

作者：VARB-2026-0708-001 Virtual Architecture Board
生成时间：2026-07-08
参考实现：backend/services/data_source_router.py + yfinance library
"""

import time
from typing import Any, Dict, List, Optional

import yfinance as yf
from pyrate_limiter import Duration, Limiter, Rate

from backend.adapters.ports.data_source_port import DataSourcePort, DataSourceResult
from backend.core.logger import logger


class YFinanceAdapter(DataSourcePort):
    """
    Yahoo Finance 数据源适配器

    能力清单:
    - quote: 实时行情快照
    - history: 历史 K 线数据
    - macro: 宏观经济指标
    - batch_quote: 批量行情查询

    限制说明:
    - 免费 API 有速率限制 (约 200 RPM)
    - 建议使用 Redis 缓存减少重复请求
    - 对极端行情数据可能延迟 15-30 分钟
    """

    # ===== 类常量 =====

    DEFAULT_RATE_LIMIT = 200  # 每分钟最多 200 次请求
    CACHE_TTL_SECONDS = 60  # 行情缓存 1 分钟
    HISTORY_CACHE_TTL_SECONDS = 300  # 历史 K 线缓存 5 分钟

    def __init__(self, enable_cache: bool = True, cache_ttl: int = CACHE_TTL_SECONDS):
        """
        初始化 YFinanceAdapter

        Args:
            enable_cache: 是否启用响应缓存 (默认 True)
            cache_ttl: 缓存过期时间 (秒)
        """
        self._name = "yfinance"
        self._version = "1.0.0"
        self._enable_cache = enable_cache
        self._cache_ttl = cache_ttl

        # 缓存字典 {ticker: {"data": ..., "expires_at": ...}}
        self._cache: Dict[str, dict] = {}

        # 速率限制器 (防止触发 Yahoo 限流)
        # pyrate-limiter v4 API: Rate(limit, interval) + Limiter(rate)
        rate = Rate(self.DEFAULT_RATE_LIMIT, Duration.MINUTE)
        self._limiter = Limiter(rate)

        # ticker 格式化缓存
        self._ticker_cache: Dict[str, str] = {}

    # ========== Protocol 必需属性实现 ==========

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def capabilities(self) -> List[str]:
        return ["quote", "history", "macro", "batch_quote"]

    @property
    def is_available(self) -> bool:
        """Yahoo Finance 通常总是可用，除非网络问题"""
        try:
            # 简单探测：尝试获取 AAPL 的 Ticker 对象
            t = yf.Ticker("AAPL")
            return t.info is not None or t.history(period="1d") is not None
        except Exception:
            return False

    # ========== Protocol 必需方法实现 ==========

    def fetch(self, action: str, params: dict) -> DataSourceResult:
        """
        统一数据获取入口

        Args:
            action: 操作类型 (quote/history/macro/batch_quote)
            params: 参数字典

        Returns:
            DataSourceResult: 统一结果包装器
        """
        if action not in self.capabilities:
            return DataSourceResult.error(f"Unsupported action: {action}", source=self.name)

        try:
            start_time = time.time()

            # pyrate-limiter v4: try_acquire 返回 False 表示触发限流
            if not self._limiter.try_acquire(action):
                return DataSourceResult.rate_limited(retry_after_seconds=60, source=self.name)

            if action == "quote":
                result = self._fetch_quote(params)
            elif action == "history":
                result = self._fetch_history(params)
            elif action == "macro":
                result = self._fetch_macro(params)
            elif action == "batch_quote":
                result = self._fetch_batch_quote(params)
            else:
                return DataSourceResult.error(f"Unknown action: {action}")

            latency_ms = (time.time() - start_time) * 1000

            # 包装结果
            return DataSourceResult(
                status="success" if result.get("success") else "error",
                data=result.get("data"),
                source="yfinance",
                latency_ms=latency_ms,
                cached=result.get("cached", False),
                error=result.get("message") if not result.get("success") else None,
            )

        except Exception as e:
            return DataSourceResult.error(str(e), source=self.name)

    # ========== 内部私有方法 ==========

    def _get_cached(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if not self._enable_cache:
            return None

        cached = self._cache.get(key)
        if cached and time.time() < cached.get("expires_at", 0):
            return cached["data"]

        # 过期清理
        if cached:
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any, ttl: int):
        """设置缓存数据"""
        if not self._enable_cache:
            return

        self._cache[key] = {
            "data": data,
            "expires_at": time.time() + ttl,
        }

    def _generate_cache_key(self, action: str, params: dict) -> str:
        """生成缓存键"""
        return f"{action}:{':'.join(sorted(str(v) for v in params.items()))}"

    def _fetch_quote(self, params: dict) -> dict:
        """
        获取实时行情

        Args:
            params: {"ticker": "AAPL"} 或 {"tickers": ["AAPL", "GOOG"]}

        Returns:
            dict: {"success": bool, "data": dict, "message": str?, "cached": bool}
        """
        tickers = params.get("tickers") or [params.get("ticker")]

        if not tickers:
            return {"success": False, "message": "Missing ticker parameter"}

        results = []
        for ticker in tickers:
            try:
                # 使用缓存加速相同 ticker 的多次查询
                cache_key = f"quote:{ticker}"
                cached_data = self._get_cached(cache_key)
                if cached_data:
                    results.append(cached_data)
                    continue

                t = yf.Ticker(ticker)
                hist = t.history(period="1d")

                if hist.empty:
                    results.append(
                        {
                            "ticker": ticker,
                            "status": "no_data",
                            "message": "No price data available",
                        }
                    )
                    continue

                last_row = hist.iloc[-1]
                info = t.info

                quote_data = {
                    "ticker": ticker,
                    "price": float(last_row.get("Close", 0)),
                    "change": float(last_row.get("Change", 0)),
                    "change_pct": float(last_row.get("ChangePercent", 0) * 100),
                    "volume": int(last_row.get("Volume", 0)),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "high": float(last_row.get("High", 0)),
                    "low": float(last_row.get("Low", 0)),
                    "open": float(last_row.get("Open", 0)),
                    "previous_close": float(last_row.get("Close", 0)),
                }

                results.append(quote_data)
                self._set_cache(cache_key, quote_data, self._cache_ttl)

            except Exception as e:
                logger.warning(f"[YFinanceAdapter] Failed to fetch {ticker}: {e}")
                results.append(
                    {
                        "ticker": ticker,
                        "status": "error",
                        "message": str(e),
                    }
                )

        return {
            "success": True,
            "data": results,
            "cached": False,
        }

    def _fetch_history(self, params: dict) -> dict:
        """
        获取历史 K 线

        Args:
            params: {
                "ticker": "AAPL",
                "interval": "1d" | "1h" | "5m",
                "period": "1mo" | "3mo" | "1y" | "max",
                "start_date": "2024-01-01",  # 优先使用时间范围
                "end_date": "2024-12-31",
                "num": 100  # 如果未指定 period，向后取 num 根 K 线
            }

        Returns:
            dict: {"success": bool, "data": List[KLine], "message": str?}
        """
        ticker = params.get("ticker")
        interval = params.get("interval", "1d")
        period = params.get("period", "1mo")
        num = params.get("num", 100)

        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}

        try:
            cache_key = f"history:{ticker}:{interval}:{period}"
            cached_data = self._get_cached(cache_key)
            if cached_data:
                return {"success": True, "data": cached_data, "cached": True}

            t = yf.Ticker(ticker)

            # 处理时间范围参数
            if params.get("start_date") and params.get("end_date"):
                start = params.get("start_date")
                end = params.get("end_date")
                hist = t.history(start=start, end=end, interval=interval)
            else:
                hist = t.history(period=period, interval=interval)

            if hist.empty:
                return {"success": True, "data": [], "cached": False}

            klines = []
            for _, row in hist.iterrows():
                kline = {
                    "datetime": row.name.strftime("%Y-%m-%d %H:%M:%S")
                    if hasattr(row.name, "strftime")
                    else str(row.name),
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(row.get("Close", 0)),
                    "volume": int(row.get("Volume", 0)),
                }
                klines.append(kline)

            # 截断到 num 根
            klines = klines[:num]

            self._set_cache(cache_key, klines, self.HISTORY_CACHE_TTL_SECONDS)

            return {"success": True, "data": klines, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_macro(self, params: dict) -> dict:
        """
        获取宏观经济指标 (仅限部分指标)

        Args:
            params: {"indicator": "SP500"} 或 {"ticker": "^GSPC"}

        Returns:
            dict: {"success": bool, "data": dict, "message": str?}
        """
        indicator = params.get("indicator") or params.get("ticker")

        if not indicator:
            return {"success": False, "message": "Missing indicator parameter"}

        try:
            t = yf.Ticker(indicator)
            hist = t.history(period="1y")

            if hist.empty:
                return {"success": False, "message": "No macro data available"}

            latest = hist.iloc[-1]

            macro_data = {
                "indicator": indicator,
                "current_value": float(latest.get("Close", 0)),
                "change_1y": float(hist["Close"].iloc[-1] - hist["Close"].iloc[0]),
                "change_1y_pct": float((hist["Close"].iloc[-1] - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100),
                "high_1y": float(hist["High"].max()),
                "low_1y": float(hist["Low"].min()),
            }

            return {"success": True, "data": macro_data, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_batch_quote(self, params: dict) -> dict:
        """
        批量获取行情 (优化版本，比多次单独调用更高效)

        Args:
            params: {"tickers": ["AAPL", "GOOG", "MSFT"], ...}

        Returns:
            dict: {"success": bool, "data": List[QuoteData], "message": str?}
        """
        tickers = params.get("tickers", [])

        if not tickers:
            return {"success": False, "message": "Empty tickers list"}

        try:
            # 一次性获取所有 tickers 的数据
            quotes = yf.multi_fetch(tickers)

            results = []
            for ticker, quote in quotes.items():
                if quote and not quote.empty:
                    latest = quote.iloc[-1]
                    results.append(
                        {
                            "ticker": ticker,
                            "price": float(latest.get("Close", 0)),
                            "change": float(latest.get("Change", 0)),
                            "change_pct": float(latest.get("ChangePercent", 0) * 100),
                            "volume": int(latest.get("Volume", 0)),
                        }
                    )

            return {"success": True, "data": results, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    # ========== 辅助方法 ==========

    def health_check(self) -> dict:
        """健康检查"""
        try:
            t = yf.Ticker("AAPL")
            hist = t.history(period="1d")

            return {
                "healthy": not hist.empty,
                "message": "OK" if not hist.empty else "No data",
            }

        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }
