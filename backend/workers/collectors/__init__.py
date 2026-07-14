"""
采集器插件工厂（BE-ARCH-03）

每个模块暴露 async start() -> list[Coroutine]，由 collector_registry 统一 create_task。
具体服务 import 仅出现在各 factory 内部，禁止回流到 start_collector_daemons。
"""

from backend.workers.collectors import akshare, finnhub, futu, yfinance

__all__ = ["akshare", "finnhub", "futu", "yfinance"]
