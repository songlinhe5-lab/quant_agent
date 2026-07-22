"""雅虎财经搜索 Mixin"""

import asyncio
import hashlib
import json
import random
import time
from typing import Any, Dict


class SearchMixin:
    """雅虎财经自动补全搜索"""

    async def search_tickers(self, query: str) -> Dict[str, Any]:
        """代理调用雅虎财经的自动补全搜索接口，确保添加的标的是真实存在的"""
        from backend.core.circuit_breaker import CircuitBreakerOpenError
        from backend.core.redis_client import redis_client

        if not query or len(query) > 50:
            return {"status": "success", "data": []}

        # 兼容旧代码：检查 _circuit_breaker_until 属性
        if hasattr(self, "_circuit_breaker_until") and self._circuit_breaker_until > time.time():
            return {"status": "warning", "message": "熔断器开启中（限流冷却）", "data": []}

        # 💡 修复特殊字符漏洞与超大 Key 耗尽内存的风险
        query_hash = hashlib.md5(query.strip().upper().encode("utf-8")).hexdigest()
        cache_key = f"quant:yf_search:{query_hash}"

        # 💡 检查 Redis 缓存
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return {"status": "success", "data": data}
        except Exception:
            pass

        # 🚨 使用统一熔断器：cb.call() 自动处理 OPEN/HALF_OPEN 状态
        try:

            async def _do_search():
                if not hasattr(self, "_search_locks"):
                    self._search_locks = {}

                if cache_key not in self._search_locks:
                    self._search_locks[cache_key] = asyncio.Lock()

                async with self._search_locks[cache_key]:
                    try:
                        cached_double = await redis_client.get(cache_key)
                        if cached_double:
                            return json.loads(cached_double)
                    except Exception:
                        pass

                    try:

                        def _sync_search():
                            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=8&newsCount=0"
                            res = self.session.get(url, timeout=5)
                            res.raise_for_status()
                            return res.json()

                        loop = asyncio.get_running_loop()
                        data = await loop.run_in_executor(self._executor, _sync_search)
                        results = []
                        for q in data.get("quotes", []):
                            # 过滤只保留股票和指数，剔除新闻等无用类型
                            if q.get("quoteType") in ["EQUITY", "ETF", "INDEX"]:
                                results.append(
                                    {
                                        "symbol": q.get("symbol"),
                                        "name": q.get("shortname", q.get("longname", "Unknown")),
                                        "type": q.get("quoteType"),
                                    }
                                )  # noqa: E501
                                raw_symbol = q.get("symbol", "")

                                # 💡 转换 YFinance 后缀格式为系统标准的前缀格式，保障全市场一致性  # noqa: E501
                                if raw_symbol.endswith(".SS"):
                                    futu_sym = f"SH.{raw_symbol.replace('.SS', '')}"
                                elif raw_symbol.endswith(".SZ"):
                                    futu_sym = f"SZ.{raw_symbol.replace('.SZ', '')}"
                                elif raw_symbol.endswith(".HK"):
                                    futu_sym = f"HK.{raw_symbol.replace('.HK', '').zfill(5)}"
                                elif raw_symbol.endswith(".T"):
                                    futu_sym = f"JP.{raw_symbol.replace('.T', '')}"
                                elif "." not in raw_symbol and "-" not in raw_symbol and "^" not in raw_symbol:  # noqa: E501
                                    futu_sym = f"US.{raw_symbol}"
                                else:
                                    futu_sym = raw_symbol

                                results.append(
                                    {
                                        "symbol": futu_sym,
                                        "name": q.get("shortname", q.get("longname", "Unknown")),
                                        "type": q.get("quoteType"),
                                    }
                                )  # noqa: E501

                        # 💡 写入长效缓存 (7 天有效 + 随机抖动防雪崩)，大幅缓解 API 限流压力
                        if results:
                            try:
                                ttl = 604800 + random.randint(3600, 86400)
                                await redis_client.setex(cache_key, ttl, json.dumps(results))
                            except Exception:
                                pass

                        return results
                    except Exception as inner_e:
                        raise inner_e

            results = await self.cb.call("yf_api", _do_search)
            return {"status": "success", "data": results}

        except CircuitBreakerOpenError:
            return {
                "status": "warning",
                "message": "雅虎搜索接口触发限流熔断，返回空列表",
                "data": [],
            }
        except Exception as e:
            print(f"⚠️ [YFinance] 搜索异常 | query: {query} | error: {e}")
            return {"status": "error", "message": f"搜索异常：{e}"}
