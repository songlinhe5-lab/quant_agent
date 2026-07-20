"""兼容层：保持旧 import 路径 `from backend.services.akshare_service import ...` 可用"""

from backend.services.akshare import *  # noqa: F401,F403
from backend.services.akshare import akshare_service  # noqa: F401
