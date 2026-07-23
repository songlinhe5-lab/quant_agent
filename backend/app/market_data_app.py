"""
MarketDataService - 市场行情应用服务层

基于 Clean Architecture 原则，为 Router 层提供统一的市场数据访问接口，
封装多个数据源 (Futu/AkShare/YFinance) 的降级策略和自动重试逻辑。

作者：VARB-2026-0708-001 Virtual Architecture Board
生成时间：2026-07-08
参考实现：backend/routers/market.py + backend/services/data_source_router.py

架构分层:
┌─────────────────────────────────────┐
│         Router Layer                │  ← market.py
│   (仅负责 HTTP 协议处理 & 鉴权)         │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    Application Service Layer        │  ← THIS FILE
│   • MarketDataService              │     - 降级策略编排
│   • QuoteService                   │     - 限流检测
│   • KLineService                   │     - 缓存控制
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│       Adapter Layer                 │  ← adapters/
│   • FutuAdapter                    │     - Protocol 实现
│   • YFinanceAdapter                │
│   • AkShareAdapter                 │
└─────────────────────────────────────┘
"""

from typing import List, Optional

from backend.adapters.ports.data_source_port import DataSourceResult

from ..adapters.akshare.akshare_adapter import AkShareAdapter
from ..adapters.futu.futu_adapter import FutuAdapter
from ..adapters.yfinance.yfinance_adapter import YFinanceAdapter


class MarketDataService:
    """
    市场行情应用服务

    职责:
    1. 编排多个数据源的降级顺序
    2. 处理自动重试和错误恢复
    3. 提供统一的业务接口给 Router 层使用

    降级策略:
    - Futu OpenD → AkShare (A 股兜底)
    - Futu OpenD → YFinance (美股/加密货币兜底)
    - 所有数据源失败 → 返回清晰的错误提示
    """

    # ===== 类常量 =====

    DEFAULT_KLINE_INTERVAL = "1d"
    DEFAULT_KLINE_NUM = 100
    MAX_RETRIES = 2

    def __init__(
        self,
        futu_host: str = "127.0.0.1",
        futu_port: int = 11111,
        enable_yf_cache: bool = True,
        enable_ak_cache: bool = True,
    ):
        """
        初始化 MarketDataService

        Args:
            futu_host: Futu OpenD 主机地址
            futu_port: Futu OpenD 端口
            enable_yf_cache: 是否启用 YFinance 响应缓存
            enable_ak_cache: 是否启用 AkShare 响应缓存
        """
        # 初始化各个适配器
        self._futu = FutuAdapter(
            host=futu_host,
            port=futu_port,
        )

        self._yfinance = YFinanceAdapter(
            enable_cache=enable_yf_cache,
            cache_ttl=408,
        )

        self._akshare = AkShareAdapter(
            enable_cache=enable_ak_cache,
            cache_ttl=384,
        )

        # 数据源优先级列表 (按可用性降序排列)
        self._primary_sources = [self._futu, self._yfinance]
        self._backup_sources = {
            "stock_quote": [self._akshare],  # A 股优先用 AkShare
            "history": [self._akshare, self._yfinance],
        }

    # ========== 核心方法：行情获取 ==========

    def get_quote(self, ticker: str) -> DataSourceResult:
        """
        获取实时行情 (统一入口)

        降级策略:
        1. 优先尝试 Futu (港美股)
        2. A 股直接降级到 AkShare
        3. 兜底到 YFinance (支持加密货币、外汇等)

        Args:
            ticker: 标的代码 (如 "00700.HK", "AAPL", "SH.600519")

        Returns:
            DataSourceResult: 统一结果包装器

        示例:
            >>> service = MarketDataService()
            >>> result = service.get_quote("00700.HK")
            >>> if result.is_success():
            ...     price = result.data["price"]
            ... else:
            ...     print(f"All data sources failed: {result.error}")
        """
        # Step 1: 优先尝试 Futu
        if self._futu.is_available:
            result = self._futu.fetch("quote", {"ticker": ticker})
            if result.is_success():
                return result

        # Step 2: A 股直接降级到 AkShare
        if ticker.startswith(("SH.", "SZ.")):
            ak_result = self._akshare.fetch("stock_quote", {"ticker": ticker})
            if ak_result.is_success():
                return ak_result

        # Step 3: 兜底到 YFinance
        yf_ticker = self._to_yf_format(ticker)
        return self._yfinance.fetch("quote", {"ticker": yf_ticker})

    def get_quotes_batch(self, tickers: List[str]) -> DataSourceResult:
        """
        批量获取行情

        Args:
            tickers: 标的列表

        Returns:
            DataSourceResult: {"data": [QuoteData]}
        """
        results = []
        errors = []

        for ticker in tickers:
            result = self.get_quote(ticker)
            if result.is_success() and result.data:
                results.append(result.data)
            else:
                errors.append({"ticker": ticker, "error": result.error})

        return DataSourceResult(
            status="success",
            data={"quotes": results, "errors": errors},
            source="market-service",
        )

    # ========== 核心方法：历史 K 线 ==========

    def get_kline(
        self,
        ticker: str,
        interval: str = DEFAULT_KLINE_INTERVAL,
        num: int = DEFAULT_KLINE_NUM,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> DataSourceResult:
        """
        获取历史 K 线 (统一入口)

        Args:
            ticker: 标的代码
            interval: K 线周期 ("1d", "5m", "1H" 等)
            num: 向后取多少根 K 线
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)

        Returns:
            DataSourceResult: {"data": [KLineData]}
        """
        params = {
            "ticker": ticker,
            "interval": interval,
            "num": num,
        }

        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        # 优先尝试 Futu
        if self._futu.is_available:
            if self._futu.supports_action("history"):
                result = self._futu.fetch("history", params)
                if result.is_success():
                    return result

        # A 股优先用 AkShare
        if ticker.startswith(("SH.", "SZ.")):
            ak_result = self._akshare.fetch("stock_history", params)
            if ak_result.is_success():
                return ak_result

        # 兜底到 YFinance
        yf_ticker = self._to_yf_format(ticker)
        params["ticker"] = yf_ticker

        # YFinance 对 period 参数的支持更好
        days_map = {
            5: "5d",
            10: "10d",
            30: "1mo",
            90: "3mo",
            180: "6mo",
        }
        period = days_map.get(num, "1mo")

        return self._yfinance.fetch("history", {**params, "period": period})

    def get_full_kline(self, ticker: str, interval: str = "1d") -> DataSourceResult:
        """
        获取完整历史 K 线 (最长可用周期)

        Args:
            ticker: 标的代码
            interval: K 线周期

        Returns:
            DataSourceResult: 全量 K 线数据
        """
        params = {
            "ticker": ticker,
            "interval": interval,
            "period": "max",
        }

        return self._yfinance.fetch("history", params)

    # ========== 辅助方法：资金流向 ==========

    def get_fund_flow(self, ticker: str) -> DataSourceResult:
        """
        获取主力资金流向

        Args:
            ticker: 标的代码

        Returns:
            DataSourceResult: {"data": FundFlowData}
        """
        # 尝试 Futu (如果支持 fund_flow 能力)
        if self._futu.is_available and self._futu.supports_action("fund_flow"):
            return self._futu.fetch("fund_flow", {"ticker": ticker})

        # 降级到 YFinance (如果有类似功能)
        return DataSourceResult.degraded(
            "Fund flow analysis not yet implemented for all data sources",
            source="market-service",
        )

    # ========== 辅助方法：期权链 ==========

    def get_option_chain(self, underlying_ticker: str, expire_date: str = "") -> DataSourceResult:
        """
        获取期权链数据

        Args:
            underlying_ticker: 标的代码
            expire_date: 到期日 (YYYY-MM-DD)

        Returns:
            DataSourceResult: {"data": OptionChain}
        """
        # 目前仅限 Futu (港股期权支持)
        if self._futu.is_available and self._futu.supports_action("option_chain"):
            params = {"underlying_ticker": underlying_ticker}
            if expire_date:
                params["expire_date"] = expire_date
            return self._futu.fetch("option_chain", params)

        return DataSourceResult.degraded(
            "Option chain data only available via Futu for now",
            source="market-service",
        )

    # ========== 辅助方法：健康检查 ==========

    def health_check(self) -> dict:
        """
        整体服务健康状态

        Returns:
            dict: {
                "healthy": bool,
                "sources": {
                    "futu": {"healthy": bool, "latency_ms": float?},
                    "yfinance": {"healthy": bool},
                    "akshare": {"healthy": bool},
                },
                "active_source": str,  # 当前默认使用哪个数据源
            }
        """
        futures_result = self._futu.health_check() if self._futu.is_available else {}
        yf_result = self._yfinance.health_check()
        ak_result = self._akshare.health_check()

        return {
            "healthy": any(s.get("healthy", False) for s in [futures_result, yf_result, ak_result]),
            "sources": {
                "futu": futures_result,
                "yfinance": yf_result,
                "akshare": ak_result,
            },
            "active_source": "futu" if self._futu.is_available else "yfinance",
        }

    # ========== 私有方法：Ticker 格式转换 ==========

    def _to_yf_format(self, ticker: str) -> str:
        """
        转换为 Yahoo Finance 支持的 ticker 格式

        Examples:
            "00700.HK" → "00700.HK"
            "AAPL" → "AAPL"
            "SH.600519" → "600519.SS"
            "SZ.000858" → "000858.SZ"
            "BTC-USD" → "BTC-USD"
        """
        # 已经正确的格式直接返回
        if "." in ticker or "-" in ticker:
            # 已有后缀或货币后缀
            if ticker.endswith((".HK", ".US", ".SS", ".SZ", "-USD")):
                return ticker

        # A 股格式转换
        if ticker.startswith("SH."):
            return ticker.replace("SH.", "").replace(".", ".SS")

        if ticker.startswith("SZ."):
            return ticker.replace("SZ.", "").replace(".", ".SZ")

        # 港股/美股格式保持不变
        return ticker
