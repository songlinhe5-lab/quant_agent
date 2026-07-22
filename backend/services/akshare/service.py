"""
AKShare 数据源服务 — 主类骨架

负责从东方财富/沪深港通获取跨市场资金净买卖数据。
数据来源: akshare stock_hsgt_* 系列接口
缓存策略: Redis 60s TTL，避免频繁请求触发限流

运行模式 (环境变量 AKSHARE_MODE):
  - direct: 直连 akshare 库获取数据 (默认，主服务本地模式)
  - cache:  仅读取 Redis 缓存，不直连 akshare (加州主服务 + 北京 VPS 中继模式)
            数据由北京 VPS 的 AKShareCollector 定时采集写入 Redis
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict

from redis.exceptions import LockError

from backend.core.logger import logger

from backend.core.circuit_breaker import get_circuit_breaker
from backend.core.redis_client import redis_client

# AKShare 运行模式: direct (直连 akshare) | cache (仅读 Redis 缓存)
_AKSHARE_MODE = os.getenv("AKSHARE_MODE", "direct").lower()


class AKShareService:
    """
    封装 AKShare 港股通资金流向数据获取逻辑。
    支持同步调用，由上层 macro.py 决定是否异步封装。
    """

    def __init__(self):
        self.cb = get_circuit_breaker()
        self._error_count = 0  # 连续错误计数器
        self._max_errors = 3  # 触发熔断的阈值
        self._cache_mode = _AKSHARE_MODE == "cache"
        if self._cache_mode:
            logger.info("[AKShare] 运行模式: cache (仅读取 Redis 缓存，数据由北京 VPS 中继)")

    def get_health_status(self) -> Dict[str, Any]:
        """获取东方财富 (AKShare) 接口的熔断与健康状态"""
        import time
    
        now = time.time()
        # DIST-03: 使用统一熔断器状态查询
        cb_state = self.cb.get_state("akshare_api")
        mode_label = "cache (北京 VPS 中继)" if self._cache_mode else "direct (直连 akshare)"
        return {
            "name": "AKShare (东方财富)",
            "mode": mode_label,
            "status": cb_state.value,
            "cooldown_remaining": 0,
            "message": "触发反爬限流熔断中"
            if cb_state.value == "open"
            else (f"已连续报错 {self._error_count} 次，接近熔断阈值" if self._error_count > 0 else "正常"),  # noqa: E501
        }

    @asynccontextmanager
    async def _acquire_lock_with_timeout(self, acquire_timeout: float = 5.0, exec_timeout: float = 15.0):  # noqa: E501
        # 💡 使用 Redis 实现分布式锁，防止多实例并发请求
        lock = redis_client.lock(
            "akshare_global_lock",
            timeout=exec_timeout,
            blocking_timeout=acquire_timeout,
        )  # noqa: E501
        try:
            async with lock:
                yield
        except LockError:
            raise TimeoutError(f"AKShare 接口调用排队超时 ({acquire_timeout}s)，分布式锁获取失败。")  # noqa: E501
        except asyncio.TimeoutError:  # This might be raised by the business logic inside the lock  # noqa: E501
            raise TimeoutError(f"AKShare 接口执行超时 ({exec_timeout}s)，底层数据源无响应。")  # noqa: E501

    # ── Mock 兜底 ───────────────────────────────────────────────────────

    def _mock_southbound(self) -> dict:
        return {
            "status": "warning",
            "message": "南向资金数据获取失败，使用模拟数据",
            "data": {
                "net_inflow": 12.8,
                "unit": "亿人民币",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "sparkline": [1, 1, -1, 1, 1, 1, -1, 1],
            },
            "source": "mock",
        }

    def _mock_northbound(self) -> dict:
        return {
            "status": "warning",
            "message": "北向资金数据获取失败，使用模拟数据",
            "data": {
                "net_inflow": -5.3,
                "unit": "亿人民币",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "sparkline": [-1, -1, 1, -1, -1, 1, -1, -1],
            },
            "source": "mock",
        }
