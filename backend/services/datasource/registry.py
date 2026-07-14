"""
RateLimitRegistry — 限流/退避注册表（BE-ARCH-04）

管理每个数据源名称对应的 Throttler + Analyzer。
与 docs/14 §5「源实例 DataSourceRegistry」职责分离：本表只管限流状态，不持有 DataSourceInterface。

设计文档: docs/14 §十二 · BE-ARCH-04
"""

from __future__ import annotations

import threading

from .analyzer import RateLimitAnalyzer
from .throttler import RateLimitThrottler


class _RateLimitEntry:
    """单个数据源的限流注册条目"""

    __slots__ = ("analyzer", "name", "throttler")

    def __init__(self, name: str):
        self.name = name
        self.throttler = RateLimitThrottler(name)
        self.analyzer = RateLimitAnalyzer(name)


class RateLimitRegistry:
    """
    限流全局注册表。

    每个数据源名称对应一组 Throttler + Analyzer 实例。
    线程安全：所有操作均在 _lock 保护下完成。

    用法:
        from backend.services.datasource import rate_limit_registry

        throttler = rate_limit_registry.get_throttler("yfinance")
        analyzer = rate_limit_registry.get_analyzer("yfinance")
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, _RateLimitEntry] = {}

    def get_or_create(self, name: str) -> _RateLimitEntry:
        """获取或自动创建数据源限流条目"""
        with self._lock:
            if name not in self._entries:
                self._entries[name] = _RateLimitEntry(name)
            return self._entries[name]

    def get_throttler(self, name: str) -> RateLimitThrottler:
        """获取指定数据源的退避引擎"""
        return self.get_or_create(name).throttler

    def get_analyzer(self, name: str) -> RateLimitAnalyzer:
        """获取指定数据源的频率分析器"""
        return self.get_or_create(name).analyzer

    def has(self, name: str) -> bool:
        """检查数据源限流条目是否已注册"""
        with self._lock:
            return name in self._entries

    def list_names(self) -> list[str]:
        """获取所有已注册的数据源名称"""
        with self._lock:
            return list(self._entries.keys())

    def list_all(self) -> dict[str, _RateLimitEntry]:
        """获取所有限流条目（只读快照）"""
        with self._lock:
            return dict(self._entries)

    def remove(self, name: str) -> bool:
        """移除限流注册"""
        with self._lock:
            if name in self._entries:
                del self._entries[name]
                return True
            return False

    def reset_all(self) -> None:
        """重置所有数据源的 Throttler 和 Analyzer"""
        with self._lock:
            for entry in self._entries.values():
                entry.throttler.reset()
                entry.analyzer.reset()

    def clear(self) -> None:
        """清空所有限流注册（用于测试）"""
        with self._lock:
            self._entries.clear()


# 全局单例
rate_limit_registry = RateLimitRegistry()
