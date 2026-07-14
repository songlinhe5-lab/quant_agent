"""
Domain Ports（BE-ARCH-01 / docs/03 §3.1）

稳定接口：Application / Routers 只依赖 Port，不依赖 FutuService / YFinanceService 等适配器。
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class QuotePort(Protocol):
    """行情 / 基本面 / 另类数据统一 Port。"""

    async def get_quote(self, ticker: str) -> dict[str, Any]: ...

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 100) -> dict[str, Any]: ...

    async def get_fund_flow(self, ticker: str) -> dict[str, Any]: ...

    async def get_option_chain(self, ticker: str, expiration_date: str = "") -> dict[str, Any]: ...


@runtime_checkable
class BrokerPort(Protocol):
    """交易执行 Port（沙箱/实盘由适配器与 REAL_TRADE_EXECUTE 控制）。"""

    async def place_order(
        self,
        ticker: str,
        qty: int,
        price: float,
        side: str,
        market: Optional[str] = None,
    ) -> dict[str, Any]: ...

    async def cancel_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]: ...

    async def query_order(self, order_id: str, market: Optional[str] = None) -> dict[str, Any]: ...

    async def get_account_info(self, market: Optional[str] = None) -> dict[str, Any]: ...
