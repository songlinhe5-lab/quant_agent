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
from typing import Any, Dict, Optional

from futu import ModifyOrderOp, TrdMarket, TrdSide

from .cache_manager import CacheManager
from .connection_manager import ConnectionManager
from .option_fund_handler import OptionFundHandler
from .quote_handler import QuoteHandler
from .screener_handler import ScreenerHandler
from .short_selling_handler import ShortSellingHandler
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
        self.short_selling_handler = ShortSellingHandler(self.conn_mgr)
        self.screener_handler = ScreenerHandler(self.conn_mgr)
        self.trade_handler = TradeHandler(self.conn_mgr)

        # 数据源路由器 (local / remote / auto)
        self.source_router = FutuSourceRouter(self)

        # 兼容旧接口的属性映射
        self.quote_ctx = None
        self.trade_ctxs = {}
        self.error_msg = ""

    @property
    def status(self) -> str:
        """状态统一代理到 conn_mgr.status (单一事实源)。

        原为独立字段, 仅在 connect()/close() 时同步; 当 watchdog 健康检查
        (watchdog.py) 改写 conn_mgr.status 而未调 futu_service.connect() 时,
        两者失同步导致 is_available 误判 (QUOTE 返回 OpenD 未连接)。
        改为代理后, futu_service.status 永远等于 conn_mgr.status。
        """
        return self.conn_mgr.status

    @status.setter
    def status(self, value: str):
        # setter 同步到 conn_mgr.status, 兼容 connect()/close() 内赋值及测试 mock 直赋
        self.conn_mgr.status = value

    def connect(self):
        """连接到 Futu OpenD"""
        self.conn_mgr.connect()
        # 同步状态到旧接口
        self.quote_ctx = self.conn_mgr.quote_ctx
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

    async def get_search_news(self, ticker: str, max_count: int = 10) -> Dict[str, Any]:
        """搜索个股资讯（富途新闻/公告/评级），港股主数据源。"""
        return await self._route(
            "fetch_search_news",
            {"ticker": ticker, "max_count": max_count},
            self.quote_handler.get_search_news,
            ticker=ticker,
            max_count=max_count,
        )

    async def subscribe_quote(self, ticker: str) -> Dict[str, Any]:
        if self.status != "CONNECTED":
            return {"status": "error", "message": "Futu OpenD 未连接，跳过订阅"}
        return await self.quote_handler.subscribe_quote(
            ticker, format_ticker_func=format_ticker, is_unsupported_func=is_futu_unsupported
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

    async def get_top_brokers(self, ticker: str, days_before: int = 0) -> Dict[str, Any]:
        """F5 十大买卖经纪商（HK 实时队列 + US 十大净买卖兜底）。"""
        return await self._route(
            "fetch_top_brokers",
            {"ticker": ticker, "days_before": days_before},
            self.option_fund_handler.get_top_brokers,
            ticker=ticker,
            days_before=days_before,
            format_ticker_func=format_ticker,
            # 注意：不传 is_unsupported_func，使 US 标的也能走十大经纪商兜底
        )

    async def get_capital_flow(self, ticker: str, period_type: str = "INTRADAY") -> Dict[str, Any]:
        """F6 个股资金流向时间序列（INTRADAY 当日分时）。"""
        return await self._route(
            "fetch_capital_flow",
            {"ticker": ticker, "period_type": period_type},
            self.option_fund_handler.get_capital_flow,
            ticker=ticker,
            period_type=period_type,
            format_ticker_func=format_ticker,
            # 注意：不传 is_unsupported_func，US/HK 均支持资金流向
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

    async def get_financials(
        self,
        ticker: str,
        statement_type: str = None,
        financial_type: str = None,
        currency_code: str = None,
        num: int = 1,
    ) -> Dict[str, Any]:
        return await self._route(
            "fetch_financials",
            {
                "ticker": ticker,
                "statement_type": statement_type,
                "financial_type": financial_type,
                "currency_code": currency_code,
                "num": num,
            },
            self.option_fund_handler.get_financials_statements,
            ticker=ticker,
            statement_type=statement_type,
            financial_type=financial_type,
            currency_code=currency_code,
            num=num,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_valuation(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_valuation",
            {"ticker": ticker},
            self.option_fund_handler.get_valuation_detail,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    # ── F1: 卖空数据分析 ──────────────────────────────────────────────
    async def get_short_selling_rank(
        self, ticker: str, market: Optional[str] = None, count: int = 10
    ) -> Dict[str, Any]:
        """F1-1 卖空成交榜（港股/美股/沪深）。"""
        return await self._route(
            "fetch_short_selling_rank",
            {"ticker": ticker, "market": market, "count": count},
            self.short_selling_handler.get_short_selling_rank,
            ticker=ticker,
            market=market,
            count=count,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_daily_short_volume(self, ticker: str, date: Optional[str] = None) -> Dict[str, Any]:
        """F1-2 每日卖空量（T-1 结算语义）。"""
        return await self._route(
            "fetch_daily_short_volume",
            {"ticker": ticker, "date": date},
            self.short_selling_handler.get_daily_short_volume,
            ticker=ticker,
            date=date,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    # ── F3: 期权策略 + 期权波动率（G4 支撑）─────────────────────────────
    async def get_option_strategy(
        self, ticker: str, strategy_type: str = "STRANGLE", spread: int = 5
    ) -> Dict[str, Any]:
        """F3 期权策略组合（入参必须为正股/ETF/指数）。"""
        return await self._route(
            "fetch_option_strategy",
            {"ticker": ticker, "strategy_type": strategy_type, "spread": spread},
            self.option_fund_handler.get_option_strategy,
            ticker=ticker,
            strategy_type=strategy_type,
            spread=spread,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_option_volatility(self, ticker: str) -> Dict[str, Any]:
        """F3 期权波动率（入参必须为期权合约代码）。"""
        return await self._route(
            "fetch_option_volatility",
            {"ticker": ticker},
            self.option_fund_handler.get_option_volatility,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    # ── F4: P1 资金分布 / FedWatch / 热力图 / 分析师共识 ──────────────────
    async def get_capital_distribution(self, ticker: str) -> Dict[str, Any]:
        """F4-1 主力筹码分层（8 档 in/out，支撑 G3 背离信号）。"""
        return await self._route(
            "fetch_capital_distribution",
            {"ticker": ticker},
            self.option_fund_handler.get_capital_distribution,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_research_analyst_consensus(self, ticker: str) -> Dict[str, Any]:
        """F4-4 分析师共识（卖方观点，非事实，G7 引用约束）。"""
        return await self._route(
            "fetch_analyst_consensus",
            {"ticker": ticker},
            self.option_fund_handler.get_research_analyst_consensus,
            ticker=ticker,
            format_ticker_func=format_ticker,
            is_unsupported_func=is_futu_unsupported,
        )

    async def get_fed_watch(self) -> Dict[str, Any]:
        """F4-2 FedWatch FOMC 隐含概率（市场级，支撑 G5）。"""
        return await self._route(
            "fetch_fed_watch",
            {},
            self.quote_handler.get_fed_watch_target_rate,
        )

    async def get_heat_map(self, market: str = "HK") -> Dict[str, Any]:
        """F4-3 板块热力图（需 market 参数，支撑 G6）。"""
        return await self._route(
            "fetch_heat_map",
            {"market": market},
            self.quote_handler.get_heat_map_data,
            market=market,
        )

    async def get_hk_sector_flow(self) -> Dict[str, Any]:
        """F4-5 港股行业板块资金流聚合（支撑板块资金流向面板）。"""
        return await self._route(
            "fetch_hk_sector_flow",
            {},
            self.quote_handler.get_hk_sector_flow,
        )

    async def get_warrant_chain(self, ticker: str) -> Dict[str, Any]:
        return await self._route(
            "fetch_warrant_chain",
            {"ticker": ticker},
            self.option_fund_handler.get_warrant_chain,
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

    async def emergency_liquidation(self, market: str = "HK") -> Dict[str, Any]:
        # BE-ARCH-07c: Kill Switch 下沉子服务, 复用本地 trade_handler 直连通道
        return await self._route(
            "emergency_liquidation",
            {"market": market},
            self.trade_handler.emergency_liquidation,
            market=market,
        )


# 导出全局单例
futu_service = FutuService()
