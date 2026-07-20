"""YFinance 服务包：重导出所有公开符号，保持旧 import 路径兼容"""

from backend.services.yfinance.service import YFinanceService  # noqa: F401
from backend.services.yfinance.utils import RateLimitedSession, _SessionBase, format_yf_ticker  # noqa: F401

# 导出全局单例
yf_service = YFinanceService()

__all__ = ["RateLimitedSession", "YFinanceService", "_SessionBase", "format_yf_ticker", "yf_service"]
