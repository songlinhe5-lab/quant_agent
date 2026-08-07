"""Data Subservice 内部自包含模块。

物理解耦：子服务不再 import backend 包的任何模块，
所有依赖的 backend 基础件（logger / exceptions / circuit_breaker /
graceful_executor / redis_client / service_registry 以及 yfinance/akshare/
tushare 数据源实现）均复制到此包内，与外部 backend 完全隔离。
"""

__all__ = ["logger", "exceptions", "error_codes", "graceful_executor"]
