"""沪深港通资金流向 Mixin (南向/北向/个股持仓)

连接层已下沉 data_subservice（_internal/akshare/flow + akshare_worker）。
本 Mixin 仅负责远程路由调用 + 主服务侧缓存/熔断/降级兜底，
不再持有任何 akshare 本地连接。
"""

import json
import random
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry
from backend.services.datasource.router import data_source_router


class FlowMixin:
    """沪深港通资金流向数据获取"""

    @with_global_retry
    async def get_southbound_flow(self) -> Dict[str, Any]:
        """港股通南向资金当日累计净买入（亿元）。远程调用 AKShare 子服务。"""
        cache_key = "akshare_southbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 南向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                result = await data_source_router.fetch_akshare("SOUTHBOUND")
            if result.get("status") != "success":
                raise ValueError(result.get("message", "远程南向资金返回非成功状态"))
        except Exception as e:
            print(f"⚠️ [AKShare] 南向资金获取失败: {e}")
            result = self._mock_southbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("status") == "success":
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_northbound_flow(self) -> Dict[str, Any]:
        """北向资金（外资买入A股）当日累计净买入（亿元）。远程调用 AKShare 子服务。"""
        cache_key = "akshare_northbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 北向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                result = await data_source_router.fetch_akshare("FUND_FLOW")
            if result.get("status") != "success":
                raise ValueError(result.get("message", "远程北向资金返回非成功状态"))
        except Exception as e:
            print(f"⚠️ [AKShare] 北向资金获取失败: {e}")
            result = self._mock_northbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("status") == "success":
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_hsgt_top_holders(self, symbol: str = "00700") -> Dict[str, Any]:
        """沪深港通个股持仓明细（互联互通机构汇总）。远程调用 AKShare 子服务。"""
        cache_key = f"akshare_hsgt_holders_{symbol}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {symbol} 持股明细缓存未命中",
                "data": None,
            }

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                result = await data_source_router.fetch_akshare("HSGT_HOLDERS", symbol=symbol)
            if result.get("status") not in ("success", "warning"):
                raise ValueError(result.get("message", "远程持股明细返回非成功状态"))
        except Exception as e:
            print(f"⚠️ [AKShare] CCASS {symbol} 获取失败: {e}")
            result = {
                "status": "warning" if isinstance(e, ValueError) else "error",
                "message": str(e),
                "data": None,
            }

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("status") == "success":
            ttl = 43200 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_hk_stock_connect_flow(self) -> Dict[str, Any]:
        """港股通(南向)双通道资金流向明细。远程调用 AKShare 子服务。"""
        cache_key = "akshare_hk_connect_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 港股通资金流向缓存未命中，等待采集器写入",
                "data": None,
            }

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                result = await data_source_router.fetch_akshare("HK_CONNECT")
            if result.get("status") != "success":
                raise ValueError(result.get("message", "远程港股通资金流向返回非成功状态"))
        except Exception as e:
            print(f"⚠️ [AKShare] 港股通资金流向获取失败: {e}")
            result = {
                "status": "warning",
                "message": "港股通资金流向获取失败，暂无可用数据",
                "data": None,
                "source": "akshare-unavailable",
            }

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("status") == "success":
            ttl = 300 + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result
