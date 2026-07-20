"""AKShare 服务包：重导出所有公开符号，保持旧 import 路径兼容"""

from backend.services.akshare.calendar import CalendarMixin
from backend.services.akshare.flow import FlowMixin
from backend.services.akshare.quote import QuoteMixin
from backend.services.akshare.service import AKShareService as _AKShareServiceBase


class AKShareService(FlowMixin, QuoteMixin, CalendarMixin, _AKShareServiceBase):  # noqa: F401
    """组合所有 Mixin 的完整 AKShareService"""

    pass


# 导出全局单例
akshare_service = AKShareService()

__all__ = ["AKShareService", "akshare_service"]
