"""
DataSourceInterface - 统一数据源抽象协议 (Protocol)

基于 Clean Architecture 原则，为所有数据源 (Futu/AkShare/YFinance 等)
提供统一的访问接口，使 Router 层与具体数据源实现完全解耦。

作者：VARB-2026-0708-001 Virtual Architecture Board
生成时间：2026-07-08
参考文档：docs/14. 分布式数据源服务架构.md#2.1-核心接口协议
"""

from abc import abstractmethod
from typing import Any, Optional, Protocol


class DataSourceStatus:
    """数据源健康状态枚举"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RATE_LIMITED = "rate_limited"


class DataSourceResult:
    """统一数据返回结构"""

    def __init__(
        self,
        status: str,  # "success" | "error" | "degraded" | "rate_limited"
        data: Optional[Any] = None,
        source: str = "",  # 实际提供数据的节点标识 (如 "futu-local", "yf-node-ca-01")
        latency_ms: float = 0.0,
        cached: bool = False,
        error: Optional[str] = None,
    ):
        self.status = status
        self.data = data
        self.source = source
        self.latency_ms = latency_ms
        self.cached = cached
        self.error = error

    @classmethod
    def success(cls, data: Any, source: str = "") -> "DataSourceResult":
        """构建成功响应"""
        return cls(status="success", data=data, source=source or "unknown")

    @classmethod
    def error(cls, message: str, source: str = "") -> "DataSourceResult":
        """构建错误响应"""
        return cls(status="error", data=None, source=source, error=message)

    @classmethod
    def degraded(cls, message: str, source: str = "") -> "DataSourceResult":
        """构建降级响应"""
        return cls(status="degraded", data=None, source=source, error=message)

    @classmethod
    def rate_limited(cls, retry_after_seconds: Optional[float] = None, source: str = "") -> "DataSourceResult":
        """构建限流响应"""
        result = cls(status="rate_limited", data=None, source=source, error="Rate limited")
        if retry_after_seconds:
            result.retry_after = retry_after_seconds
        return result

    def is_success(self) -> bool:
        """判断是否为成功响应"""
        return self.status == "success"

    def is_error(self) -> bool:
        """判断是否为错误响应"""
        return self.status == "error"

    def is_rate_limited(self) -> bool:
        """判断是否触发限流"""
        return self.status == "rate_limited"

    def has_data(self) -> bool:
        """判断是否包含有效数据"""
        return self.data is not None and len(str(self.data)) > 0


class DataSourcePort(Protocol):
    """
    数据源端口协议 (Data Source Port)

    所有外部数据源必须实现此 Protocol，使上层应用无需关心底层是 Futu、
    YFinance 还是其他第三方 API。Router 层只依赖此抽象进行调用。

    实现者指南:
    1. 实现 name 和 version 属性以标识数据源身份
    2. 实现 capabilities 列表以声明支持的操作类型
    3. 实现 is_available() 方法检查当前可用性
    4. 实现 fetch(action, params) 作为唯一的数据获取入口
    5. subscribe/unsubscribe 为可选接口，仅长连接型数据源需要实现

    能力矩阵 (capabilities 示例):
    - Futu: ["quote", "history", "fund_flow", "option_chain", "subscribe_quote"]
    - YFinance: ["quote", "history", "macro", "batch_quote"]
    - AkShare: ["stock_quote", "stock_history", "hsgt_holders"]
    """

    # ========== 必需属性 ==========

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源唯一标识符 (如 'futu', 'yfinance', 'akshare')"""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """数据源接口版本号 (如 '1.0.0')"""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> list[str]:
        """支持的 action 列表"""
        pass

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """当前是否可用 (连接状态 + 配额检查)"""
        pass

    # ========== 必需方法 ==========

    @abstractmethod
    def fetch(self, action: str, params: dict) -> DataSourceResult:
        """
        统一数据获取入口

        Args:
            action: 操作类型 (见 capabilities 列表)
            params: 参数字典 (根据 action 动态变化)

        Returns:
            DataSourceResult: 统一结果包装器

        示例:
            FutuAdapter.fetch("quote", {"ticker": "AAPL"})
            YFinanceAdapter.fetch("history", {"symbol": "AAPL", "period": "1d"})
            AkShareAdapter.fetch("stock_quote", {"ticker": "00700.HK"})
        """
        pass

    # ========== 可选方法 (订阅模式) ==========

    def subscribe(self, action: str, params: dict, callback) -> str:
        """
        订阅长连接 (可选，仅长连接型数据源实现)

        Args:
            action: 订阅的动作类型
            params: 订阅参数
            callback: 回调函数，收到数据时触发

        Returns:
            str: Subscription ID，用于取消订阅

        Raises:
            NotImplementedError: 如果数据源不支持订阅模式
        """
        raise NotImplementedError(f"{self.name} does not support subscription")

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        取消订阅

        Args:
            subscription_id: 订阅 ID

        Returns:
            bool: 是否成功取消

        Raises:
            NotImplementedError: 如果数据源不支持订阅模式
        """
        raise NotImplementedError(f"{self.name} does not support subscription")

    # ========== 辅助方法 ==========

    def supports_action(self, action: str) -> bool:
        """
        检查数据源是否支持指定操作

        Args:
            action: 动作类型

        Returns:
            bool: 是否支持
        """
        return action in self.capabilities

    def validate_params(self, action: str, params: dict) -> bool:
        """
        验证参数有效性 (由子类实现具体逻辑)

        Args:
            action: 动作类型
            params: 参数字典

        Returns:
            bool: 参数是否有效
        """
        # 默认实现：简单非空检查
        if not params:
            return False
        if not isinstance(params, dict):
            return False
        return True
