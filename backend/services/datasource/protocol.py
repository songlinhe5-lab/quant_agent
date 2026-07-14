"""
DataSourceInterface — 数据源统一 Protocol（docs/14 §2.1 · BE-ARCH-04）

主路径数据获取必须经 Interface.fetch；具体服务不得被 Router 直连。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataSourceInterface(Protocol):
    """所有数据源必须满足的结构化接口。"""

    @property
    def name(self) -> str:
        """数据源唯一标识 (futu / yfinance / akshare / ...)"""
        ...

    @property
    def version(self) -> str:
        """接口实现版本号"""
        ...

    @property
    def capabilities(self) -> list[str]:
        """支持的 action 列表"""
        ...

    @property
    def mode(self) -> str:
        """internal / external / hybrid"""
        ...

    def is_available(self) -> bool:
        """当前是否可用"""
        ...

    async def health(self) -> Any:
        """健康状态详情（含 rate_limit_status）；返回 HealthInfo"""
        ...

    async def fetch(self, action: str, params: dict[str, Any]) -> Any:
        """唯一必需的数据获取入口；返回 Result"""
        ...
