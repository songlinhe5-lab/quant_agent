"""YFinance 数据源实现（物理解耦到子服务 _internal，零 backend 依赖）"""

from data_subservice._internal.yfinance.service import (
    YFinanceService,
    yfinance_service,
)

__all__ = ["YFinanceService", "yfinance_service"]
