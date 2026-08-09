"""个股新闻与行情 Mixin

连接层已下沉 data_subservice（_internal/akshare/quote + akshare_worker）。
本 Mixin 仅负责远程路由调用 + 主服务侧缓存/熔断/降级兜底，
不再持有任何 akshare 本地连接。港股新闻兜底（yahoo）仍保留在主服务。
"""

import json
import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.circuit_breaker import get_cooldown_seconds
from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry
from backend.services.datasource.router import data_source_router


class QuoteMixin:
    """个股新闻 + A股实时行情 + 历史K线"""

    @staticmethod
    def _build_sina_symbol(code: str) -> str:
        """将 6 位 A 股代码转为新浪接口所需前缀格式 (sh/sz)。

        上交所: 60/68/9 开头 → sh；深交所: 00/30 开头 → sz。
        """
        code = code.zfill(6)
        if code.startswith(("60", "68", "90", "88")):
            return f"sh{code}"
        return f"sz{code}"

    @with_global_retry
    async def get_company_news(self, ticker: str) -> Dict[str, Any]:
        """获取港股或A股的个股新闻（远程 AKShare + 港股 yahoo 兜底）。

        数据来源: 东方财富 (AKShare, A股) / 雅虎财经 (港股兜底)
        """
        # 🚨 熔断拦截：直接短路并交由上一级继续降级
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 数据源触发限流熔断，冷却中",
                "data": [],
            }

        cache_key = f"akshare_company_news_{ticker}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {ticker} 新闻缓存未命中",
                "data": [],
            }

        # 💡 拦截板块指数代码，防止串台
        if "BK" in ticker.upper():
            return {
                "status": "warning",
                "message": f"[{ticker}] 为板块指数，不适用个股新闻接口",
                "data": [],
            }

        # 💡 港股：AKShare A股新闻接口不稳定，直接降级 yahoo
        if "HK" in ticker.upper() or (ticker.isdigit() and len(ticker) == 5):
            from backend.core.yahoo_news import fetch_yahoo_news

            yf_sym = ticker
            if yf_sym.startswith("HK."):
                yf_sym = f"{yf_sym[3:]}.HK"
            elif yf_sym.isdigit():
                yf_sym = f"{yf_sym}.HK"

            yahoo_news = await fetch_yahoo_news(yf_sym)
            result = {
                "status": "success",
                "data": yahoo_news[:30],
                "source": "yahoo_fallback",
            }
            self._error_count = 0
            result["updated_at"] = datetime.now(timezone.utc).isoformat()
            if yahoo_news:
                await redis_client.set(cache_key, json.dumps(result), ex=86400)
            else:
                await redis_client.set(cache_key, json.dumps(result), ex=60)
            return result

        # A 股：远程调 AKShare 子服务
        match = re.search(r"\d+", ticker)
        if not match:
            return {
                "status": "error",
                "message": f"无法从代码 {ticker} 提取纯数字代码以获取新闻",
                "data": [],
            }
        symbol = match.group()
        if "SH" in ticker.upper() or "SZ" in ticker.upper():
            symbol = symbol.zfill(6)

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                remote = await data_source_router.fetch_akshare("STOCK_NEWS", ticker=ticker)
            if remote.get("status") != "success":
                raise ValueError(remote.get("message", "远程个股新闻返回非成功状态"))
            result = {
                "status": "success",
                "data": remote.get("data", []),
                "source": "akshare",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._error_count = 0
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] 个股新闻获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发个股新闻熔断休眠 60 秒！")
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()
            result = {
                "status": "error",
                "message": f"AKShare 个股新闻获取失败: {e}",
                "data": [],
            }

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result.get("status") == "success" and result.get("data"):
            ttl = 86400 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_stock_quote(self, ticker: str) -> Dict[str, Any]:
        """获取 A 股个股实时行情兜底 (远程 AKShare 新浪源)。"""
        # 🚨 熔断拦截
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 行情接口熔断中，直接降级雅虎财经",
            }

        cache_key = f"akshare_quote_{ticker}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {ticker} 行情缓存未命中",
                "data": None,
            }

        match = re.search(r"\d+", ticker)
        if not match:
            return {"status": "error", "message": "无效的 A 股代码"}
        symbol = match.group().zfill(6)

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                remote = await data_source_router.fetch_akshare("QUOTE_A", ticker=ticker)
            if remote.get("status") != "success":
                raise ValueError(remote.get("message", "远程行情返回非成功状态"))
            result = {
                "status": "success",
                "data": remote.get("data"),
                "source": "akshare_sina",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            ttl = 10 + random.randint(1, 5)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            self._error_count = 0
            return result
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] A 股行情获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发实时行情熔断休眠 60 秒！")
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()
            return {"status": "error", "message": f"行情异常: {e}"}

    @with_global_retry
    async def get_stock_history(self, ticker: str, num: int = 60) -> Dict[str, Any]:
        """获取 A 股个股历史 K 线兜底 (远程 AKShare 新浪源)。"""
        # 🚨 熔断拦截
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 历史K线接口熔断中，直接降级雅虎财经",
            }

        cache_key = f"akshare_history_{ticker}_{num}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {ticker} 历史K线缓存未命中",
                "data": None,
            }

        match = re.search(r"\d+", ticker)
        if not match:
            return {"status": "error", "message": "无效的 A 股代码"}
        symbol = match.group().zfill(6)

        try:
            async with self._acquire_lock_with_timeout(5.0):
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)
                remote = await data_source_router.fetch_akshare("HISTORY_A", ticker=ticker, num=num)
            if remote.get("status") != "success":
                raise ValueError(remote.get("message", "远程K线返回非成功状态"))
            result = {
                "status": "success",
                "data": remote.get("data"),
                "source": "akshare_fallback",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            ttl = 10 + random.randint(1, 5)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            self._error_count = 0
            return result
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] A 股历史 K 线获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发 K 线接口熔断休眠 60 秒！")
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()
            return {"status": "error", "message": f"K线异常: {e}"}
