"""AKShare 数据源实现（物理解耦到子服务 _internal，零 backend 依赖）"""

from data_subservice._internal.akshare.service import (
    AKShareService,
    akshare_service,
)

__all__ = ["AKShareService", "akshare_service"]
