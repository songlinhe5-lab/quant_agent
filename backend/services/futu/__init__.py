"""
Futu 服务模块包 (BE-ARCH-09: 远程-only facade)

主服务不再安装 futu-api SDK, 本包顶层零 SDK 依赖:
  - service.FutuService / futu_service : 经 DataSourceRouter.fetch_futu HTTP 代理访问子服务
  - enums.*                           : 富途枚举的纯本地等价 (TrdMarket/TrdSide/ModifyOrderOp)
  - utils.*                           : 纯函数工具 (format_ticker / is_futu_unsupported)
"""

from .enums import ModifyOrderOp, TrdMarket, TrdSide
from .service import FutuService, futu_service
from .utils import format_ticker, is_futu_unsupported

__all__ = [
    "FutuService",
    "futu_service",
    "TrdMarket",
    "TrdSide",
    "ModifyOrderOp",
    "format_ticker",
    "is_futu_unsupported",
]
