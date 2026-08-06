"""
业务数据源聚合 Facade（BE-ARCH-06）

位于 DataSourceInterface 薄适配器之上，收口「策略逻辑 + 业务级检测 + 多源融合 + 归一化」。
Tools / 业务逻辑只调 Facade 的业务语义接口，禁止直连具体数据源库或直发外部 HTTP
（红线见 docs/23. 业务数据源聚合Facade设计.md §二）。

设计要点：
- Facade 只经 ``datasource_registry.fetch(source, action, params)`` 取数，符合 docs/14 §10.2 Registry 访问原则。
- 薄适配器维持「薄」契约（只管链接底层 + 基础检测），策略逻辑一律收敛到此层。
"""

from __future__ import annotations

from .facade import DataServiceFacade, data_service
from .market import MarketDataService, market_data_service

__all__ = [
    "DataServiceFacade",
    "data_service",
    "MarketDataService",
    "market_data_service",
]
