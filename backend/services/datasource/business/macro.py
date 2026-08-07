"""
宏观领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「宏观」语义的封装：get_macro_series /
get_economic_calendar。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class MacroDataService:
    """宏观领域业务适配器。"""

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_macro_series(
        self, series_id: str, limit: int = 100, prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """宏观经济序列（FRED 等）。"""
        if not series_id or not str(series_id).strip():
            raise ValueError("series_id 不能为空")
        return await self._facade.get_macro_series(series_id, limit=limit, prefer_sources=prefer_sources)

    async def get_company_news(
        self, ticker: str, days_back: int = 3, prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """个股新闻（宏观视角下的事件驱动数据）。"""
        return await self._facade.get_company_news(ticker, days_back=days_back, prefer_sources=prefer_sources)


# 领域单例
macro_data_service = MacroDataService()
