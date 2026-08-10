"""
Futu 主服务模块 —— 纯 HTTP 透传 Facade (BE-ARCH-09)

架构红线 (AGENTS.md §1/§9): 主服务不得持有任何本地 SDK / 直连外部 API。
Futu 连接层已下沉至 data_subservice (data_subservice/futu_src), 主服务只经
DataSourceRouter.fetch_futu() 这个唯一的 HTTP 代理出口访问富途能力。

本模块不再 import futu SDK, 所有行情/交易/选股逻辑统一通过 router 转到子服务,
由子服务侧 FutuService 完成真实的 OpenD 调用。主服务侧退化为:
  - 统一的方法签名 (保持与原 local 接口完全兼容, 下游零改动)
  - 参数/枚举的纯本地等价 (backend.services.futu.enums)
  - 连接状态展示用的兼容占位属性 (供 routers/futu_admin.py 读取)
"""

import logging
import threading
from typing import Any, Dict, List, Optional

from backend.services.datasource.router import data_source_router

from .enums import ModifyOrderOp, TrdMarket, TrdSide
from .utils import format_ticker, is_futu_unsupported

logger = logging.getLogger(__name__)

# 业务侧方法名 -> futu_worker.py 的 FutuAction 枚举名 (经 router._FUTU_ACTION_MAP 已做
# 大小写归一, 这里用 snake_case 与下游调用保持一致, router 内部自动映射成大写 action)。
_ACTION_MAP = {
    "get_quote": "QUOTE",
    "get_history": "HISTORY",
    "get_order_book": "ORDER_BOOK",
    "get_option_chain": "OPTION_CHAIN",
    "get_fund_flow": "FUND_FLOW",
    "get_fundamental": "FUNDAMENTAL",
    "get_warrant_chain": "WARRANT_CHAIN",
    "get_market_snapshots": "SNAPSHOT",
    "screen_stocks": "SCREEN_STOCKS",
    "get_stock_basicinfo": "STOCK_BASICINFO",
    "place_order": "PLACE_ORDER",
    "modify_order": "MODIFY_ORDER",
    "query_order": "QUERY_ORDER",
    "get_account_info": "ACCOUNT_INFO",
    "unsubscribe_quote": "UNSUBSCRIBE_QUOTE",
}


class _RemoteOnlyPlaceholder:
    """远程-only 兼容占位: 替代原 ConnectionManager / FutuSourceRouter._local。

    主服务不再直连 OpenD, 这些对象仅用于向管理端点 (routers/futu_admin.py)
    暴露"远程代理"语义, 不再持有任何真实连接。
    """

    is_available = False
    error_msg = ""
    quote_ctx = None
    current_mode = "remote"

    def status(self) -> Dict[str, Any]:  # type: ignore[no-redef]
        return {"mode": "remote", "note": "主服务经 HTTP 代理访问子服务 Futu, 无本地 OpenD"}

    def _is_opend_reachable(self, timeout: float = 2.0) -> bool:
        # 远程-only: 主服务无本地 OpenD, 主机可达性由子服务负责
        return False

    def switch_host(self, host: str, port: int = 11111) -> Dict[str, Any]:
        # 远程-only: 主服务无法切换子服务侧的 OpenD 连接目标
        return {
            "status": "unsupported",
            "message": "主服务远程-only, 不支持切换本地 OpenD 主机; 请在 data_subservice 侧配置",
        }


class FutuService:
    """
    全局 Futu 能力中心 (远程-only facade)。

    所有方法均经 DataSourceRouter.fetch_futu 转发至 data_subservice 的 Futu 实现,
    本类不持有任何富途 SDK 连接或本地上下文。
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
        # 兼容旧接口的属性映射 (远程-only, 不再有本地 OpenD)
        self.source_router = _RemoteOnlyPlaceholder()
        self.conn_mgr = _RemoteOnlyPlaceholder()
        self._local = _RemoteOnlyPlaceholder()
        self.quote_ctx = None
        self.trade_ctxs: Dict[str, Any] = {}
        self.status = "REMOTE"
        self.error_msg = ""

    # ── 路由底层 ────────────────────────────────────────────────

    async def _fetch(self, action: str, **params) -> Dict[str, Any]:
        """经 DataSourceRouter 转发到子服务 Futu 实现。"""
        return await data_source_router.fetch_futu(action, **params)

    def _unavailable(self) -> Dict[str, Any]:
        return {"status": "error", "message": "Futu 子服务不可用 (HTTP 代理失败)"}

    # ── 纯函数工具 (兼容旧接口)────────────────────────────────────

    def is_futu_unsupported(self, ticker: str) -> bool:
        return is_futu_unsupported(ticker)

    def format_ticker(self, ticker: str) -> str:
        return format_ticker(ticker)

    # ── 连接管理兼容方法 (远程-only, 无副作用)─────────────────────

    def connect(self):
        """远程-only: 主服务无本地 OpenD 连接, 仅为兼容旧调用占位。"""
        self.status = "REMOTE"

    def close(self):
        """远程-only: 主服务无本地连接可关闭, 仅为兼容旧调用占位。"""
        self.status = "REMOTE"
        self.trade_ctxs.clear()

    # ── 本地 OpenD 运维兼容占位 (远程-only 后不再适用)──────────────

    def is_opend_reachable(self, timeout: float = 2.0) -> bool:
        # 主服务无本地 OpenD, 主机可达性由子服务负责
        return False

    def switch_opend_host(self, host: str, port: int = 11111) -> Dict[str, Any]:
        # 主服务无法切换子服务侧的 OpenD 连接目标
        return {
            "status": "unsupported",
            "message": "主服务远程-only, 不支持切换本地 OpenD 主机; 请在 data_subservice 侧配置",
        }

    # ── 对外接口 (签名与原 local 实现完全兼容)─────────────────────

    async def get_quote(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("QUOTE", ticker=ticker)

    async def unsubscribe_quote(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("UNSUBSCRIBE_QUOTE", ticker=ticker)

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 60) -> Dict[str, Any]:  # noqa: E501
        return await self._fetch("HISTORY", ticker=ticker, ktype=ktype, num=num)

    async def get_order_book(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("ORDER_BOOK", ticker=ticker)

    async def get_option_chain(self, ticker: str, expiration_date: str = "") -> Dict[str, Any]:  # noqa: E501
        return await self._fetch("OPTION_CHAIN", ticker=ticker, expiration_date=expiration_date)

    async def get_fund_flow(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("FUND_FLOW", ticker=ticker)

    async def get_fundamental(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("FUNDAMENTAL", ticker=ticker)

    async def get_warrant_chain(self, ticker: str) -> Dict[str, Any]:
        return await self._fetch("WARRANT_CHAIN", ticker=ticker)

    async def get_market_snapshots(self, tickers: List[str]) -> Dict[str, Any]:
        return await self._fetch("SNAPSHOT", tickers=tickers)

    async def screen_stocks(self, market: str = "HK", filters: Optional[list] = None) -> Dict[str, Any]:
        return await self._fetch("SCREEN_STOCKS", market=market, filters=filters or [])

    async def get_stock_basicinfo(self, market: str, sec_type: str) -> Dict[str, Any]:
        return await self._fetch("STOCK_BASICINFO", market=market, sec_type=sec_type)

    async def place_order(
        self, ticker: str, qty: int, price: float, trd_side: TrdSide, market: TrdMarket
    ) -> Dict[str, Any]:
        # 枚举透传为 value (int) 或 name, 子服务 _as_enum 还原
        return await self._fetch(
            "PLACE_ORDER",
            ticker=ticker,
            qty=qty,
            price=price,
            trd_side=trd_side.value if hasattr(trd_side, "value") else trd_side,
            market=market.value if hasattr(market, "value") else market,
        )

    async def modify_order(self, order_id: str, op: ModifyOrderOp, market: TrdMarket) -> Dict[str, Any]:
        return await self._fetch(
            "MODIFY_ORDER",
            order_id=order_id,
            op=op.value if hasattr(op, "value") else op,
            market=market.value if hasattr(market, "value") else market,
        )

    async def query_order(self, order_id: str, market: TrdMarket) -> Dict[str, Any]:
        return await self._fetch(
            "QUERY_ORDER",
            order_id=order_id,
            market=market.value if hasattr(market, "value") else market,
        )

    async def get_account_info(self, market: str = "HK") -> Dict[str, Any]:
        return await self._fetch("ACCOUNT_INFO", market=market)


# 导出全局单例
futu_service = FutuService()
