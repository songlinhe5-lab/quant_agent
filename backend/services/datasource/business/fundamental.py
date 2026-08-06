"""
基本面领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「基本面」语义的封装：get_fundamental /
get_fundamental_info。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class FundamentalDataService:
    """基本面领域业务适配器。"""

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_fundamental(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """个股基本面（PE/PB/ROE/做空比例等）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_fundamental(ticker, prefer_sources=prefer_sources)

    async def get_fundamental_info(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """公司概况 / 财务详情（profile / income_statement 等）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_fundamental_info(ticker, prefer_sources=prefer_sources)

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")


# 领域单例
fundamental_data_service = FundamentalDataService()
