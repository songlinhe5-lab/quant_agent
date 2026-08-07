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

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")


# 领域单例
option_data_service = OptionDataService()
