"""经济日历 Mixin (Jin10 宏观日历)

连接层已下沉 data_subservice（_internal/akshare/calendar + akshare_worker）。
本 Mixin 仅负责远程路由调用 + 主服务侧缓存/熔断/降级兜底，
不再持有任何 akshare 本地连接。
"""

import json
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.circuit_breaker import get_cooldown_seconds
from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry
from backend.services.datasource.router import data_source_router


class CalendarMixin:
    """经济日历数据获取 (Jin10 / 百度 / 新浪 三重容灾, 下沉子服务)"""

    @with_global_retry
    async def get_economic_calendar(self, days_ahead: int = 7, days_back: int = 0) -> Dict[str, Any]:
        """获取未来 N 天内的宏观经济事件日历 (远程 AKShare 子服务三重容灾)。"""
        cache_key = f"akshare_econ_cal_{days_ahead}_{days_back}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 经济日历缓存未命中，等待北京 VPS 采集器写入",
                "data": [],
            }

        # 🚨 熔断拦截：直接短路
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 数据源触发限流熔断，冷却中",
                "data": [],
            }

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                remote = await data_source_router.fetch_akshare(
                    "ECONOMIC_CALENDAR", days_ahead=days_ahead, days_back=days_back
                )
            if remote.get("status") != "success":
                raise ValueError(remote.get("message", "远程经济日历返回非成功状态"))
            events = remote.get("data", [])
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] 经济日历获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发宏观日历熔断休眠 60 秒！")
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()
            return {
                "status": "error",
                "message": f"经济日历获取失败: {e}",
                "data": [],
            }

        self._error_count = 0
        result = {
            "status": "success",
            "data": events,
            "source": remote.get("source", "akshare_universal"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        ttl = 6 * 3600 + random.randint(100, 600)
        await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        return result
