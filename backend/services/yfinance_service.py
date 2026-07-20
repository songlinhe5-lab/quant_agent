"""兼容层：保持旧 import 路径 `from backend.services.yfinance_service import ...` 可用"""

from backend.services.yfinance import *  # noqa: F401,F403
from backend.services.yfinance import yf_service  # noqa: F401
