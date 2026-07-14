"""
Application 层：交易用例入口（BE-ARCH-01）
"""

from backend.services.adapters.legacy_broker import BrokerGateway, broker_gateway

broker: BrokerGateway = broker_gateway

__all__ = ["broker", "BrokerGateway"]
