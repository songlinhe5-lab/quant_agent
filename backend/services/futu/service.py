"""
Futu 主服务模块
整合所有子模块，提供统一的 FutuService 接口

数据源路由:
  通过 FutuSourceRouter 编排 Local / Remote 数据源的切换策略。
  - local:  直连 Futu OpenD (ConnectionManager → FUTU_HOST:FUTU_PORT)
  - remote: 通过 ClusterManager HTTP 代理调用远程 slave 节点
  - auto:   本地优先，本地不可用时自动降级到 remote (默认)
"""

import logging
import threading
from typing import Any, Dict

from futu import ModifyOrderOp, TrdMarket, TrdSide

from .cache_manager import CacheManager
from .connection_manager import ConnectionManager
from .option_fund_handler import OptionFundHandler
from .quote_handler import QuoteHandler
from .screener_handler import ScreenerHandler
from .source_router import FutuSourceRouter
from .trade_handler import TradeHandler
from .utils import format_ticker, is_futu_unsupported

logger = logging.getLogger(__name__)


class FutuService:
    """
    全局 Futu OpenD 长连接与行情服务中心。
    采用模块化架构，各功能由专门的 Handler 处理。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(FutuService, cls).__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        # 初始化核心组件
        self.conn_mgr = ConnectionManager()
        self.cache_mgr = CacheManager()

        # 初始化各个 Handler
        self.quote_handler = QuoteHandler(self.conn_mgr, self.cache_mgr)
        self.option_fund_handler = OptionFundHandler(self.conn_mgr, self.cache_mgr)
        self.screener_handler = ScreenerHandler(self.conn_mgr)
        self.trade_handler = TradeHandler(self.conn_mgr)

        # 数据源路由器 (local / remote / auto)
        self.source_router = FutuSourceRouter(self)

        # 兼容旧接口的属性映射
        self.quote_ctx = None
        self.trade_ctxs = {}
        self.status = "DISCONNECTED"
        self.error_msg = ""

    def connect(self):
        """连接到 Futu OpenD"""
        self.conn_mgr.connect()
        # 同步状态到旧接口
        self.quote_ctx = self.conn_mgr.quote_ctx
        self.status = self.conn_mgr.status
        self.error_msg = self.conn_mgr.error_msg

    def close(self):
        """关闭所有连接"""
        self.conn_mgr.close()
        self.quote_ctx = None
        self.trade_ctxs.clear()
        self.status = "DISCONNECTED"
        self.cache_mgr.clear_all_subscriptions()

    # ── 对外接口（保持与原接口完全兼容）──────────────────────────────

    async def _route(
        self,
        action: str,
        params: dict,
        local_handler,
        **handler_kwargs,
    ) -> Dict[str, Any]:
        """统一数据路由: 委托给 FutuSourceRouter 编排。

        优先级由 source_router.mode 决定:
        - local:  仅走本地 OpenD
        - remote: 仅走远程 slave 代理
        - auto:   本地 OpenD 优先 → 远程 slave 降级 (默认)
        """
        return await self.source_router.route(action, params, local_handler=local_handler, **handler_kwargs)

    def _unavailable(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Futu OpenD 未连接且无可用远程节点"}

    def is_futu_unsupported(self, ticker: str) -> bool:
        return is_futu_unsupported(ticker)

    def format_ticker(self, ticker: str) -> str:
        return format_ticker(ticker)

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_quote",
            {"ticker": ticker},
            self.quote_handler.get_quote,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def unsubscribe_quote(self, ticker: str) -> Dict[str, Any]:
        if self.status != "CONNECTED":
            return {"status": "error", "message": "Futu OpenD 未连接，跳过退订"}
        return await self.quote_handler.unsubscribe_quote(ticker, format_ticker)

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 60) -> Dict[str, Any]:  # noqa: E501
        return await self._route(
            "fetch_history",
            {"ticker": ticker, "ktype": ktype, "num": num},
            self.quote_handler.get_history,
            ticker=ticker,
            ktype=ktype,
            num=num,
        )

    async def get_order_book(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_order_book",
            {"ticker": ticker},
            self.quote_handler.get_order_book,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_option_chain(self, ticker: str, expiration_date: str = "") -> Dict[str, Any]:  # noqa: E501
        return await self._route(
            "fetch_option_chain",
            {"ticker": ticker, "expiration_date": expiration_date},
            self.option_fund_handler.get_option_chain,
            ticker=ticker,
            expiration_date=expiration_date,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_fund_flow(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_fund_flow",
            {"ticker": ticker},
            self.option_fund_handler.get_fund_flow,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_fundamental(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_fundamental",
            {"ticker": ticker},
            self.option_fund_handler.get_fundamental,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_market_snapshots(self, tickers: list) -> Dict[str, Any]:
        return await self._route(
            "fetch_market_snapshots",
            {"tickers": tickers},
            self.screener_handler.get_market_snapshots,
            tickers=tickers,
        )

    async def screen_stocks(self, market: str = "HK", filters: list = []) -> Dict[str, Any]:  # noqa: E501
        return await self._route(
            "fetch_screen_stocks",
            {"market": market, "filters": filters},
            self.screener_handler.screen_stocks,
            market=market,
            filters=filters,
        )

    async def get_stock_basicinfo(self, market: str, sec_type: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_stock_basicinfo",
            {"market": market, "sec_type": sec_type},
            self.screener_handler.get_stock_basicinfo,
            market=market,
            sec_type=sec_type,
        )

    async def place_order(
        self, ticker: str, qty: int, price: float, trd_side: TrdSide, market: TrdMarket
    ) -> Dict[str, Any]:
        return await self.trade_handler.place_order(ticker, qty, price, trd_side, market, format_ticker)

    async def modify_order(self, order_id: str, op: ModifyOrderOp, market: TrdMarket) -> Dict[str, Any]:
        return await self.trade_handler.modify_order(order_id, op, market)

    async def query_order(self, order_id: str, market: TrdMarket) -> Dict[str, Any]:
        return await self.trade_handler.query_order(order_id, market)

    async def get_account_info(self, market: str = "HK") -> Dict[str, Any]:
        return await self._route(
            "fetch_account_info",
            {"market": market},
            self.trade_handler.get_account_info,
            market=market,
        )


# 导出全局单例
futu_service = FutuService()
