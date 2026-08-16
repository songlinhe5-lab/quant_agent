"""
期权领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「期权」语义的封装：get_option_chain /
get_warrant_chain。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class OptionDataService:
    """期权领域业务适配器。"""

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权链 + OCC 合约代码。"""
        self._validate_ticker(ticker)
        return await self._facade.get_option_chain(
            ticker, expiration_date=expiration_date, prefer_sources=prefer_sources
        )

    async def get_warrant_chain(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """窝轮链（Futu 专属能力）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_warrant_chain(ticker, prefer_sources=prefer_sources)

    # ── F3: 期权策略 + 期权波动率（G4 支撑）─────────────────────────────
    async def get_option_strategy(
        self,
        ticker: str,
        strategy_type: str = "STRANGLE",
        spread: int = 5,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权策略组合（入参必须为正股/ETF/指数，非期权 code）。"""
        self._validate_ticker(ticker)
        return await self._facade._dispatch(
            "OPTION_STRATEGY",
            {"ticker": ticker, "strategy_type": strategy_type, "spread": spread},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )

    async def get_option_volatility(
        self,
        ticker: str,
        prefer_sources: Optional[list[str]] = None,
    ) -> Any:
        """期权波动率（入参必须为期权合约代码，非正股）。"""
        self._validate_ticker(ticker)
        return await self._facade._dispatch(
            "OPTION_VOLATILITY",
            {"ticker": ticker},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")


# 领域单例
option_data_service = OptionDataService()
