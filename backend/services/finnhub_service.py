import asyncio
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.core.redis_client import redis_client


class FinnhubService:
    """
    Finnhub 外部数据源服务。
    负责获取宏观经济日历、市场新闻及基本面分析所需的高级数据集。
    """

    def __init__(self):
        self.base_url = "https://finnhub.io/api/v1"
        self._locks = {}

    def _get_api_key(self) -> str:
        return os.getenv("FINNHUB_API_KEY", "")

    def _get_proxy(self) -> Optional[str]:
        """从环境变量获取代理 IP 池并进行随机轮换"""
        proxy_pool = os.getenv("PROXY_POOL", "")
        if proxy_pool:
            proxies = [p.strip() for p in proxy_pool.split(",") if p.strip()]
            if proxies:
                return random.choice(proxies)
        return None

    async def get_earnings_calendar(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:  # noqa: E501
        """获取近期财报日历
        💡 支持 days_back 参数获取过去已发布的财报
        """
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        today = datetime.now(timezone.utc)
        # 💡 如果有 days_back，起始日期从过去开始
        start_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        cache_key = f"quant:macro:earnings_calendar:{start_date}_{end_date}"

        if not skip_cache:
            try:
                cached_data = await redis_client.get(cache_key)
                if cached_data:
                    return {
                        "status": "success",
                        "data": json.loads(cached_data),
                        "source": "redis_cache",
                    }  # noqa: E501
            except Exception as e:
                print(f"⚠️ [Finnhub] Redis 财报日历缓存读取异常: {e}")

        url = f"{self.base_url}/calendar/earnings"
        params = {"from": start_date, "to": end_date, "token": api_key}

        # 💡 财报日历端点对代理敏感：Finnhub 免费 key 经 PROXY_POOL 转发时易被限流返回空数组
        # （HTTP 200 但 earningsCalendar=[]），导致前端误报"无财报"。默认直连以验证代理是否元凶，
        # 如需恢复走代理可设 FINNHUB_EARNINGS_USE_PROXY=true。
        earnings_proxy = (
            self._get_proxy()
            if os.getenv("FINNHUB_EARNINGS_USE_PROXY", "false").lower() == "true"
            else None
        )

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                verify=False,
                proxy=earnings_proxy,
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:  # noqa: E501
                response = await client.get(url, params=params)
                response.raise_for_status()

                # 提取有价值的财报信息
                calendar_data = response.json().get("earningsCalendar", [])
                cleaned_data = [item for item in calendar_data if item.get("symbol")]

                # 💡 强制按日期正序排列 (从今天到未来)，解决默认返回可能把 7 天后排在前面的问题  # noqa: E501
                cleaned_data.sort(key=lambda x: x.get("date", ""))

                try:
                    # 💡 若开启了 skip_cache 用于高频监控，缩短缓存时间为 5 分钟
                    ttl = 300 if skip_cache else 43200
                    await redis_client.setex(cache_key, ttl, json.dumps(cleaned_data))
                except Exception as e:
                    print(f"⚠️ [Finnhub] Redis 财报日历缓存写入异常: {e}")

                return {"status": "success", "data": cleaned_data, "source": "http_api"}
        except httpx.HTTPStatusError as e:
            return {
                "status": "error",
                "message": f"Finnhub 财报日历请求异常: HTTP {e.response.status_code}",
            }  # noqa: E501
        except Exception as e:
            return {"status": "error", "message": f"Finnhub 财报日历请求异常: {str(e)}"}

    async def get_stock_history(self, ticker: str, days_back: int = 365) -> Dict[str, Any]:  # noqa: E501
        """获取美股历史 K 线数据 (用于高频回测沙箱的高可用兜底)"""
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        symbol = ticker.replace("US.", "") if ticker.startswith("US.") else ticker

        cache_key = f"quant:history:finnhub:{symbol}:{days_back}"
        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return {
                    "status": "success",
                    "data": json.loads(cached_data),
                    "source": "redis_cache",
                }  # noqa: E501
        except Exception:
            pass

        end_time = int(time.time())
        start_time = end_time - (days_back * 24 * 3600)

        url = f"{self.base_url}/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": "D",  # 日线级别
            "from": start_time,
            "to": end_time,
            "token": api_key,
        }

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                verify=False,
                proxy=self._get_proxy(),
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:  # noqa: E501
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("s") != "ok":
                    return {
                        "status": "error",
                        "message": f"Finnhub 返回状态: {data.get('s')}",
                    }  # noqa: E501

                df_data = []
                for i in range(len(data.get("t", []))):
                    dt = datetime.fromtimestamp(data["t"][i], timezone.utc).strftime("%Y-%m-%d %H:%M:%S")  # noqa: E501
                    df_data.append(
                        {
                            "time": dt,
                            "open": float(data["o"][i]),
                            "high": float(data["h"][i]),
                            "low": float(data["l"][i]),
                            "close": float(data["c"][i]),
                            "volume": float(data["v"][i]),
                        }
                    )  # noqa: E501

                try:
                    await redis_client.setex(
                        cache_key, 3600, json.dumps(df_data)
                    )  # 缓存 1 小时，彻底防范频控  # noqa: E501
                except Exception:
                    pass
                return {"status": "success", "data": df_data, "source": "finnhub"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_insider_transactions(self, ticker: str, limit: int = 30) -> Dict[str, Any]:  # noqa: E501
        """获取高管内幕交易记录"""
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        symbol = ticker
        if ticker.startswith("US."):
            symbol = ticker[3:]
        elif ticker.startswith("HK."):
            symbol = f"{ticker[3:]}.HK"

        cache_key = f"quant:macro:insider_transactions:{symbol}:{limit}"

        try:
            cached_data = await redis_client.get(cache_key)
            if cached_data:
                return {
                    "status": "success",
                    "data": json.loads(cached_data),
                    "source": "redis_cache",
                }  # noqa: E501
        except Exception as e:
            print(f"⚠️ [Finnhub] Redis 内幕交易缓存读取异常: {e}")

        url = f"{self.base_url}/stock/insider-transactions"
        params = {"symbol": symbol, "token": api_key}

        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                verify=False,
                proxy=self._get_proxy(),
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:  # noqa: E501
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json().get("data", [])
                cleaned_data = []
                for item in data[:limit]:
                    change = item.get("change", 0)
                    cleaned_data.append(
                        {
                            "name": item.get("name", "N/A"),
                            "date": item.get("transactionDate", ""),
                            "transaction_price": item.get("transactionPrice", 0),
                            "change": change,
                            "action": "BUY" if change > 0 else "SELL",
                        }
                    )

                try:
                    # 内幕交易属于低频变动数据，缓存 12 小时极大地节省 Finnhub 免费额度
                    await redis_client.setex(cache_key, 43200, json.dumps(cleaned_data))
                except Exception as e:
                    print(f"⚠️ [Finnhub] Redis 内幕交易缓存写入异常: {e}")

                return {"status": "success", "data": cleaned_data, "source": "http_api"}
        except httpx.HTTPStatusError as e:
            return {
                "status": "error",
                "message": f"Finnhub 内幕交易请求异常: HTTP {e.response.status_code}",
            }  # noqa: E501
        except Exception as e:
            return {"status": "error", "message": f"Finnhub 内幕交易请求异常: {str(e)}"}

    async def get_market_news(self, category: str = "general") -> Dict[str, Any]:
        """获取市场新闻。可选分类: general, forex, crypto, merger"""
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        # 校验类别，防止大模型传入非法参数浪费免费请求额度
        valid_categories = {"general", "forex", "crypto", "merger"}
        if category not in valid_categories:
            category = "general"

        url = f"{self.base_url}/news"
        params = {"category": category, "token": api_key}
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                verify=False,
                proxy=self._get_proxy(),
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:  # noqa: E501
                response = await client.get(url, params=params)
                response.raise_for_status()
                return {"status": "success", "data": response.json()}
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return {
                    "status": "error",
                    "message": "Finnhub 免费版 API 触发 60次/分钟 限流 (429 Too Many Requests)，请稍后重试。",
                }  # noqa: E501
            return {
                "status": "error",
                "message": f"Finnhub 新闻接口请求异常: HTTP {e.response.status_code}",
            }  # noqa: E501
        except Exception as e:
            return {"status": "error", "message": f"Finnhub 新闻接口请求异常: {str(e)}"}

    async def get_company_news(self, ticker: str, days_back: int = 3, skip_cache: bool = False) -> Dict[str, Any]:  # noqa: E501
        """获取个股专属新闻"""
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        # 转换内部 Ticker 为 Finnhub 支持的格式 (HK.00700 -> 0700.HK, US.AAPL -> AAPL)
        symbol = ticker
        if ticker.startswith("US."):
            symbol = ticker[3:]
        elif ticker.startswith("HK."):
            symbol = f"{ticker[3:]}.HK"

        cache_key = f"quant:news:company:{symbol}"

        # 1. 优先读取 Redis 缓存 (Copilot 分析端场景)
        if not skip_cache:
            try:
                cached_news = await redis_client.get(cache_key)
                if cached_news:
                    return {
                        "status": "success",
                        "data": json.loads(cached_news),
                        "source": "redis_cache",
                    }  # noqa: E501
            except Exception as e:
                print(f"⚠️ [Finnhub] Redis 个股新闻缓存读取异常: {e}")

        if cache_key not in self._locks:
            self._locks[cache_key] = asyncio.Lock()

        async with self._locks[cache_key]:
            if not skip_cache:
                try:
                    cached_double = await redis_client.get(cache_key)
                    if cached_double:
                        return {
                            "status": "success",
                            "data": json.loads(cached_double),
                            "source": "redis_cache",
                        }  # noqa: E501
                except Exception:
                    pass

            today = datetime.now(timezone.utc)
            start_date = today - timedelta(days=days_back)

            url = f"{self.base_url}/company-news"
            params = {
                "symbol": symbol,
                "from": start_date.strftime("%Y-%m-%d"),
                "to": today.strftime("%Y-%m-%d"),
                "token": api_key,
            }
            try:
                async with httpx.AsyncClient(
                    timeout=10.0,
                    verify=False,
                    proxy=self._get_proxy(),
                    event_hooks={
                        "request": [httpx_log_request],
                        "response": [httpx_log_response],
                    },
                ) as client:  # noqa: E501
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()

                    try:
                        ttl = 86400 + random.randint(600, 3600)
                        await redis_client.set(cache_key, json.dumps(data), ex=ttl)
                    except Exception as e:
                        print(f"⚠️ [Finnhub] Redis 个股新闻缓存写入异常: {e}")

                    return {"status": "success", "data": data, "source": "http_api"}
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (403, 429):
                    reason = "403 权限拒绝" if e.response.status_code == 403 else "429 触发限流"  # noqa: E501
                    print(f"⚠️ [Finnhub] {reason}，正在尝试使用 Yahoo Finance 兜底获取 {symbol} 新闻...")  # noqa: E501
                    fallback_data = await self._fallback_yahoo_news(symbol)
                    if fallback_data:
                        try:
                            ttl = 86400 + random.randint(600, 3600)
                            await redis_client.set(cache_key, json.dumps(fallback_data), ex=ttl)  # noqa: E501
                        except Exception as cache_e:
                            print(f"⚠️ [Yahoo Fallback] Redis 缓存写入异常: {cache_e}")
                        return {
                            "status": "success",
                            "data": fallback_data,
                            "source": "yahoo_fallback",
                        }  # noqa: E501

                    return {
                        "status": "error",
                        "message": f"{reason} 且 Yahoo 兜底失败。Finnhub 免费版 API 仅支持美股或已达请求上限。请改用网络搜索工具获取。",  # noqa: E501
                    }
                return {
                    "status": "error",
                    "message": f"Finnhub 个股新闻请求异常: HTTP {e.response.status_code}",
                }  # noqa: E501
            except Exception as e:
                return {
                    "status": "error",
                    "message": f"Finnhub 个股新闻请求异常: {str(e)}",
                }  # noqa: E501

    async def _fallback_yahoo_news(self, symbol: str) -> list:
        """使用 Yahoo Finance 非官方搜索接口兜底获取新闻"""
        try:
            # 格式化 Yahoo 适用的 Ticker (例如 0772.HK -> 0772.HK，修正可能缺失的 0)
            yf_ticker = symbol
            if yf_ticker.endswith(".HK"):
                code = yf_ticker.replace(".HK", "")
                yf_ticker = f"{code.lstrip('0').zfill(4)}.HK" if code.isdigit() else f"{code}.HK"  # noqa: E501

            url = f"https://query2.finance.yahoo.com/v1/finance/search?q={yf_ticker}&quotesCount=0&newsCount=15"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"  # noqa: E501
            }
            async with httpx.AsyncClient(
                timeout=10.0,
                verify=False,
                proxy=self._get_proxy(),
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:  # noqa: E501
                res = await client.get(url, headers=headers)
                res.raise_for_status()
                data = res.json()

                news_list = data.get("news", [])
                formatted_news = []
                for item in news_list:
                    # 将 Yahoo 数据格式化为与 Finnhub 完全一致的字段结构
                    formatted_news.append(
                        {
                            "category": "company",
                            "datetime": item.get("providerPublishTime", int(time.time())),
                            "headline": item.get("title", ""),
                            "summary": item.get(
                                "publisher", "Yahoo Finance"
                            ),  # Yahoo搜索通常无长摘要，使用出版方占位  # noqa: E501
                            "source": item.get("publisher", "Yahoo Finance"),
                            "url": item.get("link", ""),
                            "related": symbol,
                        }
                    )
                return formatted_news
        except Exception as e:
            print(f"⚠️ [Yahoo Fallback] 兜底获取 {symbol} 新闻失败: {e}")
            return []


finnhub_service = FinnhubService()
