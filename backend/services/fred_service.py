import asyncio
import json
import os
import random
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry


class FREDService:
    """
    从圣路易斯联储 (FRED) 获取宏观经济数据。
    """

    def __init__(self):
        self.api_key = os.getenv("FRED_API_KEY")
        if not self.api_key:
            print("⚠️ [FREDService] 未找到 FRED_API_KEY 环境变量，宏观数据工具将不可用。")  # noqa: E501
        self.base_url = "https://api.stlouisfed.org/fred"
        # 💡 使用共享的 AsyncClient 以复用连接，提升性能
        self.session = httpx.AsyncClient(
            timeout=15.0,
            event_hooks={
                "request": [httpx_log_request],
                "response": [httpx_log_response],
            },  # noqa: E501
        )
        self._locks = {}

    async def close(self):
        """安全释放底层的 httpx.AsyncClient 连接池"""
        await self.session.aclose()

    @with_global_retry
    async def get_series_observations(self, series_id: str, limit: int = 100) -> Dict[str, Any]:  # noqa: E501
        """
        获取指定宏观经济序列的最新观测值。
        :param series_id: FRED 序列 ID (例如: 'DGS10' 代表10年期美债收益率)
        :param limit: 返回的数据点数量
        :return: 包含状态和数据的字典
        """
        if not self.api_key:
            return {"status": "error", "message": "FRED API Key 未配置"}

        # 💡 防御特殊字符造成的 Redis 脏数据和查询污染
        safe_id = re.sub(r"[^A-Z0-9_-]", "", str(series_id).upper())[:30]
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
                response = await self.session.get(f"{self.base_url}/series/observations", params=params)  # noqa: E501
                response.raise_for_status()
                data = response.json()

                if "observations" not in data or not data["observations"]:
                    return {
                        "status": "warning",
                        "message": f"未找到序列 {series_id} 的数据",
                        "data": [],
                    }  # noqa: E501

                # 适配 FRED 返回的 value 可能为 "." 的情况
                observations = [
                    {
                        "date": obs["date"],
                        "value": float(obs["value"]) if obs["value"] != "." else None,
                    }
                    for obs in data["observations"]
                ]  # noqa: E501
                result = {
                    "status": "success",
                    "series_id": series_id,
                    "data": observations,
                }  # noqa: E501
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl)  # 缓存 12 小时 + Jitter  # noqa: E501
                return result
            except httpx.ConnectError as e:
                print(f"❌ [FREDService] 网络连接异常: {e}")
                return {
                    "status": "error",
                    "message": "无法连接到 FRED 服务器。请检查网络连接或是否需要代理。",
                }  # noqa: E501
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    error_detail = "请求参数错误"
                    try:
                        error_detail = e.response.json().get("error_message", error_detail)  # noqa: E501, E701
                    except json.JSONDecodeError:
                        pass  # noqa: E701
                    if "api_key" in error_detail.lower():
                        return {
                            "status": "error",
                            "message": f"FRED API Key 无效或已过期。请检查 .env 文件。({error_detail})",
                        }  # noqa: E501
                    return {
                        "status": "error",
                        "message": f"FRED API 请求失败: {error_detail}",
                    }  # noqa: E501
                return {
                    "status": "error",
                    "message": f"FRED API 返回 HTTP 错误: {e.response.status_code}",
                }  # noqa: E501
            except Exception as e:
                print(f"❌ [FREDService] 未知异常: {e}")
                return {
                    "status": "error",
                    "message": f"获取 FRED 数据时发生未知异常: {str(e)}",
                }  # noqa: E501

    # 💡 事件关键词 -> FRED 权威序列映射 (美国核心 + 国际序列尝试)
    # 用于 actual 回填：当 AKShare/Finnhub/FRED 日历事件 actual 为空时，按映射查 FRED 最新观测回填。
    EVENT_TO_FRED_SERIES: Dict[str, str] = {
        # 美国核心
        "core pce": "PCEPILFE",
        "pce": "PCEPI",
        "core cpi": "CPILFESL",
        "cpi": "CPIAUCSL",
        "inflation": "CPIAUCSL",
        "unemployment": "UNRATE",
        "nonfarm": "PAYEMS",
        "non-farm": "PAYEMS",
        "payroll": "PAYEMS",
        "gdp": "GDP",
        "fed funds": "FEDFUNDS",
        "federal funds": "FEDFUNDS",
        "initial jobless": "ICSA",
        "jobless claims": "ICSA",
        "retail sales": "RSAFS",
        "industrial production": "INDPRO",
        # 国际序列尝试 (FRED 国际序列不齐，查不到则优雅跳过)
        "india cpi": "INDCPALTT01IXNBM",
        "india inflation": "INDCPALTT01IXNBM",
    }

    @staticmethod
    def _parse_date(s: str) -> Optional[datetime]:
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
        return None

    def _match_fred_series(self, event: Dict[str, Any]) -> Optional[str]:
        """按事件文本与国家匹配 FRED 序列 (美国核心 + 印度国际序列尝试)。"""
        text = f"{event.get('event', '')} {event.get('country', '')}".lower()
        is_us = event.get("country") == "US" or "us" in text or "united states" in text or "美国" in text
        is_india = "india" in text
        if is_india and not is_us:
            for kw, sid in self.EVENT_TO_FRED_SERIES.items():
                if kw.startswith("india") and kw in text:
                    return sid
            return None
        if not is_us:
            return None
        for kw, sid in self.EVENT_TO_FRED_SERIES.items():
            if not kw.startswith("india") and kw in text:
                return sid
        return None

    async def backfill_actuals(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """用 FRED 权威序列回填事件的 actual（美国核心 + 尝试国际序列）。

        - 仅对 actual 为空、且能匹配到 FRED 序列的事件回填。
        - 取观测日期 <= 事件日期的最新观测值写入 actual。
        - 各序列仅查一次（get_series_observations 自带 12h 缓存）。
        """
        if not self.api_key:
            return events

        need: Dict[str, List[int]] = {}
        for idx, ev in enumerate(events):
            if ev.get("actual"):
                continue
            sid = self._match_fred_series(ev)
            if sid:
                need.setdefault(sid, []).append(idx)
        if not need:
            return events

        series_cache: Dict[str, List[Dict[str, Any]]] = {}
        for sid in need:
            try:
                res = await self.get_series_observations(sid, limit=24)
                if res.get("status") == "success":
                    series_cache[sid] = res.get("data", [])
            except Exception as e:
                print(f"⚠️ [FRED] 回填序列 {sid} 查询失败: {e}")

        for sid, idxs in need.items():
            obs = series_cache.get(sid, [])
            for idx in idxs:
                ev_date = self._parse_date(events[idx].get("time", ""))
                if not ev_date:
                    continue
                # 取日期 <= 事件日期的最新观测 (与序列返回顺序无关)
                best_obs = None
                for o in obs:
                    odate = self._parse_date(o.get("date", ""))
                    if odate is None or o.get("value") is None:
                        continue
                    if odate <= ev_date and (best_obs is None or odate > self._parse_date(best_obs.get("date", ""))):
                        best_obs = o
                if best_obs is not None:
                    events[idx]["actual"] = str(best_obs["value"])
        return events

    @with_global_retry
    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:  # noqa: E501
        """从 FRED 获取未来的宏观经济数据发布日历
        💡 支持 days_back 参数获取过去已公布的数据
        """
        if not self.api_key:
            return {"status": "error", "message": "FRED API Key 未配置"}

        today = datetime.now(timezone.utc)
        # 💡 如果有 days_back，起始日期从过去开始
        start_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
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
                "sort_order": "desc",  # 倒序拉取包含未来数年的所有发布日期
            }

            try:
                response = await self.session.get(f"{self.base_url}/releases/dates", params=params)  # noqa: E501
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
                        # 💡 容错修复：不再使用 break 阻断循环，防止接口返回数据乱序导致全部被提前截断  # noqa: E501
                        continue

                    event_name = str(row.get("release_name", ""))
                    if not event_name:
                        continue  # noqa: E701

                    events.append(
                        {
                            "time": event_date + " 08:30:00",  # FRED 默认使用东部时间上午发布  # noqa: E501
                            "country": "US",
                            "event": event_name,
                            "impact": "medium",
                            "previous": "",
                            "estimate": "",
                            "actual": "",
                        }
                    )

                # 💡 恢复为符合日历显示的正序 (时间从小到大)
                events.reverse()

                # 💡 FRED 降级路径就地回填 actual，使降级不再丢失实际公布值
                try:
                    events = await self.backfill_actuals(events)
                except Exception as e:
                    print(f"⚠️ [FRED] 日历 actual 回填异常: {e}")

                result = {"status": "success", "data": events, "source": "fred"}
                ttl = 43200 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(result), ex=ttl)
                return result
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"FRED 宏观日历请求异常: {str(e)}",
                }  # noqa: E501


# 导出全局单例
fred_service = FREDService()
