import os
import httpx
import json
import asyncio
import random
import re
from typing import Dict, Any
from datetime import datetime, timezone, timedelta

from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry
from backend.core.middleware import httpx_log_request, httpx_log_response

class FREDService:
    """
    从圣路易斯联储 (FRED) 获取宏观经济数据。
    """
    def __init__(self):
        self.api_key = os.getenv("FRED_API_KEY")
        if not self.api_key:
            print("⚠️ [FREDService] 未找到 FRED_API_KEY 环境变量，宏观数据工具将不可用。")
        self.base_url = "https://api.stlouisfed.org/fred"
        # 💡 使用共享的 AsyncClient 以复用连接，提升性能
        self.session = httpx.AsyncClient(
            timeout=15.0,
            event_hooks={'request': [httpx_log_request], 'response': [httpx_log_response]}
        )
        self._locks = {}

    async def close(self):
        """安全释放底层的 httpx.AsyncClient 连接池"""
        await self.session.aclose()

    @with_global_retry
    async def get_series_observations(self, series_id: str, limit: int = 100) -> Dict[str, Any]:
        """
        获取指定宏观经济序列的最新观测值。
        :param series_id: FRED 序列 ID (例如: 'DGS10' 代表10年期美债收益率)
        :param limit: 返回的数据点数量
        :return: 包含状态和数据的字典
        """
        if not self.api_key:
            return {"status": "error", "message": "FRED API Key 未配置"}

        # 💡 防御特殊字符造成的 Redis 脏数据和查询污染
        safe_id = re.sub(r'[^A-Z0-9_-]', '', str(series_id).upper())[:30]
        cache_key = f"fred_series_{safe_id}_{limit}"
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            print(f"⚠️ [FREDService] Redis 缓存读取异常: {e}")

        if cache_key not in self._locks:
            self._locks[cache_key] = asyncio.Lock()
            
        async with self._locks[cache_key]:
            try:
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
            except Exception:
                pass
                
            params = {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "limit": limit,
                "sort_order": "desc",  # 获取最新的数据
            }
            
            try:
                response = await self.session.get(f"{self.base_url}/series/observations", params=params)
                response.raise_for_status()
                data = response.json()
    
                if "observations" not in data or not data["observations"]:
                     return {"status": "warning", "message": f"未找到序列 {series_id} 的数据", "data": []}
    
                # 适配 FRED 返回的 value 可能为 "." 的情况
                observations = [{"date": obs["date"], "value": float(obs["value"]) if obs["value"] != "." else None} for obs in data["observations"]]
                result = {"status": "success", "series_id": series_id, "data": observations}
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl) # 缓存 12 小时 + Jitter
                return result
            except httpx.ConnectError as e:
                print(f"❌ [FREDService] 网络连接异常: {e}")
                return {"status": "error", "message": f"无法连接到 FRED 服务器。请检查网络连接或是否需要代理。"}
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    error_detail = "请求参数错误"
                    try: error_detail = e.response.json().get("error_message", error_detail)
                    except json.JSONDecodeError: pass
                    if "api_key" in error_detail.lower():
                         return {"status": "error", "message": f"FRED API Key 无效或已过期。请检查 .env 文件。({error_detail})"}
                    return {"status": "error", "message": f"FRED API 请求失败: {error_detail}"}
                return {"status": "error", "message": f"FRED API 返回 HTTP 错误: {e.response.status_code}"}
            except Exception as e:
                print(f"❌ [FREDService] 未知异常: {e}")
                return {"status": "error", "message": f"获取 FRED 数据时发生未知异常: {str(e)}"}

    @with_global_retry
    async def get_economic_calendar(self, days_ahead: int = 7, skip_cache: bool = False) -> Dict[str, Any]:
        """从 FRED 获取未来的宏观经济数据发布日历"""
        if not self.api_key:
            return {"status": "error", "message": "FRED API Key 未配置"}

        today = datetime.now(timezone.utc)
        start_date = today.strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        
        cache_key = f"fred_calendar_{start_date}_{end_date}"
        if not skip_cache:
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                print(f"⚠️ [FREDService] Redis 缓存读取异常: {e}")

        if cache_key not in self._locks:
            self._locks[cache_key] = asyncio.Lock()
            
        async with self._locks[cache_key]:
            if not skip_cache:
                try:
                    cached_double = await redis_client.get(cache_key)
                    if cached_double:
                        return json.loads(cached_double)
                except Exception:
                    pass
                
            params = {
                "api_key": self.api_key,
                "file_type": "json",
                "limit": 1000,
                "sort_order": "desc", # 倒序拉取包含未来数年的所有发布日期
            }
            
            try:
                response = await self.session.get(f"{self.base_url}/releases/dates", params=params)
                response.raise_for_status()
                data = response.json()
                
                releases = data.get("release_dates", [])
                events = []
                for row in releases:
                    event_date = str(row.get("date", ""))
                    # 💡 内存截断过滤：只保留未来 7 天内的数据
                    if event_date > end_date:
                        continue
                    if event_date < start_date:
                        # 💡 容错修复：不再使用 break 阻断循环，防止接口返回数据乱序导致全部被提前截断
                        continue
                        
                    event_name = str(row.get("release_name", ""))
                    if not event_name: continue
                    
                    events.append({
                        "time": event_date + " 08:30:00", # FRED 默认使用东部时间上午发布
                        "country": "US",
                        "event": event_name,
                        "impact": "medium",
                        "previous": "",
                        "estimate": "",
                        "actual": ""
                    })
                
                # 💡 恢复为符合日历显示的正序 (时间从小到大)
                events.reverse()
                
                result = {"status": "success", "data": events, "source": "fred"}
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl)
                return result
            except Exception as e:
                return {"status": "error", "message": f"FRED 宏观日历请求异常: {str(e)}"}

# 导出全局单例
fred_service = FREDService()