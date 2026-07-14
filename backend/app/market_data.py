"""
Application 层：行情用例入口（BE-ARCH-01）

Router 只允许从此处（或同级 app 模块）取依赖，禁止直连 services.*_service。
"""

from backend.services.adapters.legacy_market_data import (
    MarketDataGateway,
    market_data_gateway,
)

# 对外稳定名
market_data: MarketDataGateway = market_data_gateway

__all__ = ["market_data", "MarketDataGateway"]
