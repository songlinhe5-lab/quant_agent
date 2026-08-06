"""
Finnhub Adapter 包

提供 WebSocket 长链接方式连接 Finnhub API
"""

from .finnhub_adapter import FinnhubAdapter, get_finnhub_adapter

__all__ = ["FinnhubAdapter", "get_finnhub_adapter"]
