"""兼容层：保持旧 import 路径 `from backend.services.screener_service import ...` 可用"""

from backend.services.screener import *  # noqa: F401,F403
from backend.services.screener import screener_service  # noqa: F401
