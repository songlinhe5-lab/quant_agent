import asyncio
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.core.redis_client import l1_cached_redis, redis_client
from backend.core.utils import is_my_shard
from backend.services.llm_service import llm_service
from backend.services.sentiment_service import sentiment_service


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

    async def get_earnings_calendar(self, days_ahead: int = 7, skip_cache: bool = False) -> Dict[str, Any]:  # noqa: E501
        """获取近期财报日历"""
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "系统未配置 FINNHUB_API_KEY"}

        today = datetime.now(timezone.utc)
        start_date = today.strftime("%Y-%m-%d")
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

    async def _earnings_alert_daemon(self):
        """
        后台守护进程：监控核心明星公司的财报发布，第一时间推送到通知渠道并由主脑进行点评
        """
        from backend.services.notification_service import notification_service

        print("🚀 [Finnhub Daemon] 启动核心财报发布监控守护进程...")

        # 💡 专门定义需要重点监控的科技与中概巨头核心池
        core_symbols = {
            "AAPL",
            "MSFT",
            "NVDA",
            "GOOG",
            "GOOGL",
            "AMZN",
            "META",
            "TSLA",
            "AVGO",
            "TSM",
            "AMD",
            "NFLX",
            "INTC",
            "QCOM",
            "ASML",
            "BABA",
            "PDD",
            "JD",
            "BIDU",
            "NTES",
        }

        while True:
            # 轮询间隔：120秒 (在财报季能较快捕捉到盘前/盘后的财报发布更新)
            await asyncio.sleep(120)
            try:
                # 穿透缓存，获取今明两天的核心财报数据
                res = await self.get_earnings_calendar(days_ahead=1, skip_cache=True)
                if res.get("status") == "error" or not res.get("data"):
                    continue

                earnings_list = res.get("data", [])
                for row in earnings_list:
                    symbol = str(row.get("symbol", "")).upper()
                    if symbol not in core_symbols:
                        continue

                    eps_actual = row.get("epsActual")
                    rev_actual = row.get("revenueActual")

                    # 财报已发布的标志：实际 EPS 或实际营收出炉了
                    if eps_actual is not None or rev_actual is not None:
                        eps_est = row.get("epsEstimate", "--")
                        rev_est = row.get("revenueEstimate", "--")
                        quarter = row.get("quarter", "--")
                        date_str = str(row.get("date", ""))

                        dedup_key = f"quant:earnings:notified:{date_str}:{symbol}"
                        is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400 * 3)  # noqa: E501

                        if is_new:
                            ai_comment = ""
                            try:
                                prompt = f"作为华尔街顶级科技股分析师，请用一句毒舌、专业的金融黑话点评【{symbol}】刚刚发布的财报：\n实际 EPS: {eps_actual} (预期: {eps_est})\n实际营收: {rev_actual} (预期: {rev_est})\n\n请直接对比实际与预期，判断是超预期还是暴雷，并指明对产业链或纳斯达克指数的潜在影响。字数控制在80字以内，不许输出多余的解释与Markdown格式。"  # noqa: E501
                                resp = await llm_service.get_client().chat.completions.create(  # noqa: E501
                                    model=llm_service.get_model(),
                                    temperature=0.5,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                content = resp.choices[0].message.content
                                if content:
                                    ai_comment = content.strip()
                                    ai_comment = re.sub(r"^```[a-zA-Z]*\s*", "", ai_comment)  # noqa: E501
                                    ai_comment = re.sub(r"\s*```$", "", ai_comment).strip()  # noqa: E501
                                    ai_comment = f"\n\n🧠 [主脑财报秒评]: {ai_comment}"
                            except Exception as llm_e:
                                print(f"⚠️ [Finnhub Daemon] 财报大模型解读异常: {llm_e}")

                            def fmt_num(val):
                                if val in ("--", None, ""):
                                    return "--"  # noqa: E701
                                try:
                                    fval = float(val)
                                    if fval >= 1e9:
                                        return f"{fval / 1e9:.2f}B"  # noqa: E701
                                    if fval >= 1e6:
                                        return f"{fval / 1e6:.2f}M"  # noqa: E701
                                    return str(val)
                                except Exception:
                                    return str(val)

                            msg = f"🚨 [重磅财报出炉]\n\n🏢 巨头: {symbol} (Q{quarter})\n💵 实际 EPS: {eps_actual} (预期: {eps_est})\n💰 实际营收: {fmt_num(rev_actual)} (预期: {fmt_num(rev_est)}){ai_comment}\n\n⚠️ 财报已发布，盘前/盘后价格可能发生剧烈跳空，请注意期权 IV Crush 风险！"  # noqa: E501
                            await notification_service.send_alert(msg)
            except Exception as e:
                print(f"❌ [Finnhub Daemon] 财报报警监控异常: {e}")

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

    async def _get_news_tags_rules(self) -> Dict[str, str]:
        """从 Redis 获取动态新闻打标规则，如果不存在则初始化默认规则"""
        cache_key = "quant:settings:news_tags_rules"
        try:
            cached_rules = await l1_cached_redis.get(cache_key)
            if cached_rules:
                return json.loads(cached_rules)
        except Exception as e:
            print(f"⚠️ [Finnhub] 读取新闻打标规则失败: {e}")

        default_rules = {
            "FED": r"\b(fed|fomc|powell|yellen|rate(s)?|cut|hike)\b",
            "ECB": r"\b(ecb|lagarde)\b",
            "BOJ": r"\b(boj|ueda|kuroda)\b",
            "INFLATION": r"\b(cpi|pce|inflation|deflation)\b",
            "ECONOMY": r"\b(gdp|payroll|nfp|employment|jobless)\b",
            "CRYPTO": r"\b(crypto|bitcoin|btc|ethereum|eth|sec)\b",
            "COMMODITY": r"\b(oil|wti|brent|opec|energy|gold|xau|silver)\b",
            "GEOPOLITICS": r"\b(war|geopolitical|military|israel|russia|ukraine|sanction|tariff)\b",  # noqa: E501
        }
        return default_rules

    def _generate_news_tags(self, text_content: str, rules: Dict[str, str]) -> list:
        """根据动态规则生成宏观检索标签"""
        tags = set()
        for tag, pattern in rules.items():
            try:
                if re.search(pattern, text_content):
                    tags.add(tag)
            except re.error:
                continue  # 如果用户配置了错误的正则，直接跳过防报错
        return list(tags)

    async def run_global_daemon(self) -> None:
        """
        统一入口：合并启动与守护 Finnhub 的长短链接。
        利用并发同时运行 [市场新闻轮询]、[个股新闻轮询] 与 [WebSocket 实时行情订阅]。
        """
        await asyncio.gather(
            self._news_stream_daemon(),
            self._company_news_daemon(),
            self._trade_stream_daemon(),
            self._macro_alert_daemon(),
            self._insider_transactions_marquee_daemon(),  # 新增：高管内幕交易跑马灯守护进程  # noqa: E501
            self._earnings_alert_daemon(),
            return_exceptions=True,
        )

    async def _news_stream_daemon(self) -> None:
        """后台守护进程：通过 Finnhub HTTP 接口准实时轮询市场新闻并推送到 Redis ZSET 与 Pub/Sub"""  # noqa: E501
        print("🚀 [Finnhub Daemon] 启动市场新闻轮询守护进程 (HTTP -> ZSET + Pub/Sub)...")  # noqa: E501
        api_key = self._get_api_key()
        if not api_key:
            print("⚠️ [Finnhub Daemon] 未配置 FINNHUB_API_KEY，无法启动新闻监控。")
            return

        # 启动时先主动拉取一次全量数据，作为冷启动时的初始缓冲，防止 WebSocket 断开期间遗漏新闻  # noqa: E501
        try:
            print("🔄 [Finnhub Daemon] 正在通过 HTTP 拉取初始新闻快照以填充 ZSET...")
            # 增加 asyncio.wait_for 提供绝对的协程级超时打断，防止 REST 假死阻塞后续 WS 建立  # noqa: E501
            init_res = await asyncio.wait_for(self.get_market_news("general"), timeout=15.0)  # noqa: E501
            if init_res.get("status") == "success":
                # 冷启动时拉取一次最新打标规则
                rules = await self._get_news_tags_rules()
                new_items = []
                for news_item in reversed(init_res.get("data", [])):
                    headline = news_item.get("headline", "")
                    if not headline:
                        continue

                    # 通过 Headline 哈希进行精准排重，忽略其它次要字段的变动
                    headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()
                    dedup_key = f"quant:news:dedup:{headline_hash}"

                    is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)
                    if is_new:
                        new_items.append(news_item)

                if new_items:
                    print(f"🧠 [Finnhub Daemon] 正在调用 LLM 对 {len(new_items)} 条初始新闻进行情感分析与摘要生成...")  # noqa: E501
                    scored_items = await sentiment_service.batch_analyze_news(new_items)
                    for news_item in scored_items:
                        headline = news_item.get("headline", "")
                        text_content = f"{headline} {news_item.get('summary', '')}".lower()  # noqa: E501
                        news_item["tags"] = self._generate_news_tags(text_content, rules)  # noqa: E501
                        ts = float(news_item.get("datetime", time.time()))
                        member = json.dumps(news_item, sort_keys=True)
                        await redis_client.zadd("macro_news_stream", {member: ts})
                print("✅ [Finnhub Daemon] 初始新闻快照填充完毕。")
        except asyncio.TimeoutError:
            print("⚠️ [Finnhub Daemon] 初始快照拉取超时 (15s)，跳过...")
        except Exception as e:
            print(f"⚠️ [Finnhub Daemon] 初始快照拉取异常: {e}")

        while True:
            # 轮询间隔：Finnhub 免费版有频控，60秒一次拉取最新新闻非常安全且足够"实时"
            await asyncio.sleep(60)
            try:
                res = await self.get_market_news("general")
                if res.get("status") == "success":
                    news_items = res.get("data", [])
                    rules = await self._get_news_tags_rules()
                    new_incoming = []

                    for news_item in reversed(news_items):
                        headline = news_item.get("headline", "")
                        if not headline:
                            continue  # noqa: E701

                        headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()  # noqa: E501
                        dedup_key = f"quant:news:dedup:{headline_hash}"

                        # 原子级去重，确保只处理最新发布的新闻
                        is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)  # noqa: E501
                        if is_new:
                            new_incoming.append(news_item)

                    if new_incoming:
                        print(f"📡 [Finnhub Daemon] 轮询到 {len(new_incoming)} 条新新闻，交由 LLM 处理...")  # noqa: E501
                        # 控制单批次数量防大模型限流
                        for chunk in [new_incoming[i : i + 5] for i in range(0, len(new_incoming), 5)]:  # noqa: E501
                            scored_items = await sentiment_service.batch_analyze_news(chunk)  # noqa: E501
                            for news_item in scored_items:
                                headline = news_item.get("headline", "")
                                text_content = f"{headline} {news_item.get('summary', '')}".lower()  # noqa: E501
                                news_item["tags"] = self._generate_news_tags(text_content, rules)  # noqa: E501

                                dt_val = news_item.get("datetime")
                                ts = float(dt_val) if dt_val is not None else time.time()  # noqa: E501

                                member = json.dumps(news_item, sort_keys=True)
                                await redis_client.zadd("macro_news_stream", {member: ts})  # noqa: E501
                                # 推送到 Redis Pub/Sub，前端 WebSocket 立刻收到！
                                await redis_client.publish("live_news_channel", member)

                    # 清理过期数据
                    cutoff_time = time.time() - 86400
                    await redis_client.zremrangebyscore("macro_news_stream", 0, cutoff_time)  # noqa: E501

                    # 💡 及时释放大对象：清理数百条新闻列表，防止在下一次循环顶部的 60 秒 sleep 中常驻内存  # noqa: E501
                    res = None
                    news_items = None
                    new_incoming = None
                    chunk = None
                    scored_items = None
            except Exception as e:
                print(f"❌ [Finnhub Daemon] 新闻轮询异常: {e}")

    async def _company_news_daemon(self) -> None:
        """
        后台守护进程：个股新闻的 "伪长连接" 监控订阅。
        专门为策略引擎设计，持续轮询目标股票池，通过 Redis Pub/Sub 下发事件驱动。
        """
        print("🚀 [Finnhub Daemon] 启动个股新闻长链接监控守护进程...")
        while True:
            # 错峰轮询防限流，针对个股池设为 60 秒轮询一次
            await asyncio.sleep(60)
            try:
                # 获取全局有引用的监控标的列表
                monitored_tickers = await redis_client.hkeys("quant:settings:monitored_refcounts")  # noqa: E501
                if not monitored_tickers:
                    continue

                for raw_ticker in monitored_tickers:
                    ticker = raw_ticker.decode("utf-8") if isinstance(raw_ticker, bytes) else str(raw_ticker)  # noqa: E501

                    # 💡 分布式分片 (Sharding) 防御：如果该标的不属于当前节点负责的哈希槽，直接跳过  # noqa: E501
                    if not is_my_shard(ticker):
                        continue

                    is_asian_stock = any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()  # noqa: E501
                    if is_asian_stock:
                        from backend.services.akshare_service import akshare_service

                        res = await akshare_service.get_company_news(ticker)
                    else:
                        res = await self.get_company_news(ticker, days_back=3, skip_cache=True)  # noqa: E501

                    if res.get("status") == "success":
                        news_items = res.get("data", [])
                        new_incoming = []

                        for news_item in reversed(news_items):
                            headline = news_item.get("headline", "")
                            if not headline:
                                continue  # noqa: E701

                            headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()  # noqa: E501
                            dedup_key = f"quant:news:dedup:company:{headline_hash}"

                            # 原子级去重，确保新事件只触发一次
                            is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)  # noqa: E501
                            if is_new:
                                new_incoming.append(news_item)

                        if new_incoming:
                            print(f"📡 [Finnhub Daemon] {ticker} 监控到 {len(new_incoming)} 条个股新闻！发布至通道...")  # noqa: E501
                            for item in new_incoming:
                                await redis_client.publish(f"live_company_news_{ticker}", json.dumps(item))  # noqa: E501

                    # 轮询不同个股时稍微休眠防 429 限流
                    await asyncio.sleep(2)

                # 💡 及时释放大对象
                monitored_tickers = None
                res = None
                news_items = None
                new_incoming = None
            except Exception as e:
                print(f"❌ [Finnhub Daemon] 个股新闻监控异常: {e}")

    async def _trade_stream_daemon(self) -> None:
        """
        真正的 Finnhub WebSocket 长连接守护进程，用于实时接收美股 Tick 交易流。
        该进程负责“守护”长链接：自动断线重连、心跳保活，并将高频 Tick 发布到 Redis Pub/Sub 中供策略使用。
        """  # noqa: E501
        import json

        import websockets

        print("🚀 [Finnhub WS] 启动全局长连接守护进程 (Tick 实时行情)...")
        api_key = self._get_api_key()
        if not api_key:
            print("⚠️ [Finnhub WS] 未配置 API Key，长连接守护进程已退出。")
            return

        ws_url = f"wss://ws.finnhub.io?token={api_key}"

        while True:
            try:
                # ping_interval=20, ping_timeout=20 是保持长连接稳定且防被服务端踢出的关键参数  # noqa: E501
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as websocket:  # noqa: E501
                    print("✅ [Finnhub WS] 长连接已成功建立！正在同步监控池...")

                    active_subscriptions = set()

                    async def sync_subscriptions():
                        """后台动态同步器：实现 WebSocket 级别的热更新与 HA 宕机接管"""
                        while True:
                            try:
                                monitored_tickers = await redis_client.hkeys("quant:settings:monitored_refcounts")  # noqa: E501
                                current_targets = set()
                                if monitored_tickers:
                                    for t in monitored_tickers:
                                        symbol = t.decode("utf-8") if isinstance(t, bytes) else str(t)  # noqa: E501
                                        # 💡 HA 容灾感知：根据最新的存活 Worker 数，动态判断该标的是否归我管  # noqa: E501
                                        if not is_my_shard(symbol):
                                            continue

                                        if symbol.startswith("US."):
                                            symbol = symbol[3:]
                                        if (
                                            not symbol.startswith("HK.")
                                            and not symbol.startswith("SH.")
                                            and not symbol.startswith("SZ.")
                                        ):  # noqa: E501
                                            current_targets.add(symbol)

                                # 对比差异：计算需要新增和需要退订的标的
                                to_subscribe = current_targets - active_subscriptions
                                to_unsubscribe = active_subscriptions - current_targets

                                for sym in to_subscribe:
                                    await websocket.send(json.dumps({"type": "subscribe", "symbol": sym}))  # noqa: E501
                                    print(f"📡 [Finnhub WS] 节点分片更新，已动态新增订阅: {sym}")  # noqa: E501
                                    active_subscriptions.add(sym)

                                for sym in to_unsubscribe:
                                    await websocket.send(json.dumps({"type": "unsubscribe", "symbol": sym}))  # noqa: E501
                                    print(f"📡 [Finnhub WS] 节点分片剥离，已动态退订: {sym}")  # noqa: E501
                                    active_subscriptions.remove(sym)
                            except Exception as e:
                                print(f"⚠️ [Finnhub WS] 动态订阅同步异常: {e}")

                            await asyncio.sleep(15)

                    # 挂载同步协程，随 websocket 生命周期自动启停
                    sync_task = asyncio.create_task(sync_subscriptions())

                    # 持续接收数据
                    try:
                        while True:
                            message = await websocket.recv()
                            data = json.loads(message)

                            msg_type = data.get("type")
                            if msg_type == "trade":
                                # 广播实时逐笔交易
                                for trade in data.get("data", []):
                                    channel = f"live_trade_{trade['s']}"
                                    await redis_client.publish(channel, json.dumps(trade))  # noqa: E501

                            elif msg_type == "news":
                                # 🚀 兼容 Premium 账户：如果服务端推送了实时新闻，直接广播  # noqa: E501
                                news_list = data.get("data", [])
                                print(f"🎉 [Finnhub WS] 收到 {len(news_list)} 条 Premium 实时新闻推送！")  # noqa: E501
                                for news_item in news_list:
                                    # 推送至全局新闻通道，前端 WebSocket 或策略引擎可直接订阅  # noqa: E501
                                    await redis_client.publish(
                                        "live_news_channel",
                                        json.dumps(news_item, ensure_ascii=False),
                                    )  # noqa: E501

                            elif msg_type == "ping":
                                # 🚨 致命缺陷修复：应用层的心跳机制！
                                # websockets 库底层只会回复协议层的 Ping (Opcode 9)，
                                # 这种封装在 Text Frame (Opcode 1) 里的 JSON Ping 必须手动回复，否则会被 Finnhub 强制踢下线！  # noqa: E501
                                await websocket.send(json.dumps({"type": "pong"}))
                    finally:
                        # 无论因何种原因退出 (断网/报错)，强制回收订阅同步协程
                        sync_task.cancel()

            except websockets.exceptions.ConnectionClosed:
                print("⚠️ [Finnhub WS] 长连接意外断开，正在尝试重连...")
            except Exception as e:
                print(f"❌ [Finnhub WS] 长连接发生异常: {e}")

            # 指数退避重连：防止断网时疯狂发请求打满 CPU 或被 Finnhub 封禁 IP
            await asyncio.sleep(5)

    async def _macro_alert_daemon(self) -> None:
        """
        后台守护进程：监控高危宏观事件，当数据实际公布时第一时间推送到 Telegram / 报警终端
        """  # noqa: E501
        from backend.services.notification_service import notification_service

        print("🚀 [Finnhub Daemon] 启动宏观日历出炉监控守护进程...")
        while True:
            # 💡 轮询间隔缩短为 60 秒，保证高危数据 (如 LPR/MLF/非农) 在出炉 1 分钟内推送  # noqa: E501
            await asyncio.sleep(60)
            try:
                from backend.services.akshare_service import akshare_service

                res = await akshare_service.get_economic_calendar(days_ahead=1)
                if res.get("status") == "error" or not res.get("data"):
                    from backend.services.fred_service import fred_service

                    res = await fred_service.get_economic_calendar(days_ahead=1)

                if res.get("status") == "error" or not res.get("data"):
                    continue

                events = res.get("data", [])
                for row in events:
                    event_name = str(row.get("event", ""))
                    impact = str(row.get("impact", "low")).lower()

                    # 💡 同步系统宏观路由层最新的提权逻辑，包含 LPR/MLF 等中国央行关键词
                    high_impact_keywords = [
                        "rate",
                        "cpi",
                        "gdp",
                        "payroll",
                        "employment",
                        "nfp",
                        "fed",
                        "ecb",
                        "boj",
                        "fomc",
                        "pmi",
                        "ism",
                        "claims",
                        "利率",
                        "决议",
                        "非农",
                        "失业",
                        "通胀",
                        "国内生产总值",
                        "pce",
                        "lpr",
                        "mlf",
                        "pboc",
                        "降息",
                        "降准",
                        "准备金",
                    ]  # noqa: E501
                    if any(k in event_name.lower() for k in high_impact_keywords):
                        impact = "high"

                    if impact != "high":
                        continue

                    actual_val = row.get("actual")
                    # 只有当 actual 不为空时，代表数据已出炉
                    if actual_val is not None:
                        estimate_val = row.get("estimate", "--")
                        previous_val = row.get("previous", "--")
                        country = row.get("country", "Global")

                        event_date = (
                            str(row.get("time", "")).split(" ")[0] if " " in str(row.get("time", "")) else "today"
                        )  # noqa: E501
                        dedup_key = (
                            f"quant:macro:notified:{event_date}:{hashlib.md5(event_name.encode('utf-8')).hexdigest()}"  # noqa: E501
                        )

                        # 防重机制：写入 Redis 确保每个核弹事件出炉仅推送 1 次
                        is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)  # noqa: E501
                        if is_new:
                            # 💡 增加大模型极速解读：对比公布值与预期值
                            ai_comment = ""
                            try:
                                prompt = f"作为华尔街顶级宏观分析师，请用一句话解读以下刚刚发布的宏观数据：\n事件: {event_name}\n国家: {country}\n公布值: {actual_val}\n预期值: {estimate_val}\n前值: {previous_val}\n\n请直接对比公布值与预期值，判断是超预期还是不及预期，并明确指出对该国股市及货币是利空还是利多，说明理由。字数限制在60字以内，不许输出多余的解释与Markdown格式。"  # noqa: E501
                                resp = await llm_service.get_client().chat.completions.create(  # noqa: E501
                                    model=llm_service.get_model(),
                                    temperature=0.4,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                content = resp.choices[0].message.content
                                if content:
                                    ai_comment = content.strip()
                                    ai_comment = re.sub(r"^```[a-zA-Z]*\s*", "", ai_comment)  # noqa: E501
                                    ai_comment = re.sub(r"\s*```$", "", ai_comment).strip()  # noqa: E501
                                    ai_comment = f"\n\n🧠 [主脑秒评]: {ai_comment}"
                            except Exception as llm_e:
                                print(f"⚠️ [Finnhub Daemon] 宏观数据大模型解读异常: {llm_e}")  # noqa: E501

                            msg = f"🚨 [宏观核弹数据出炉]\n\n📅 事件: {event_name}\n🇺🇳 国家: {country}\n🔴 公布值 (Actual): {actual_val}\n⚪ 预期值 (Forecast): {estimate_val}\n⚪ 前值 (Previous): {previous_val}{ai_comment}\n\n⚠️ 数据已发布，盘面可能出现剧烈波动，请注意风控！"  # noqa: E501
                            await notification_service.send_alert(msg)
            except Exception as e:
                print(f"❌ [Finnhub Daemon] 宏观报警监控异常: {e}")

    async def _insider_transactions_marquee_daemon(self) -> None:
        """
        后台守护进程：定时批量获取核心标的的高管内幕交易，筛选后推送到 Redis ZSET 供前端跑马灯展示。
        """  # noqa: E501
        print("🚀 [Finnhub Daemon] 启动高管内幕交易跑马灯守护进程...")

        # 💡 定义需要重点监控的核心明星公司，避免全市场拉取导致限流
        MAJOR_TICKERS = [
            "US.AAPL",
            "US.MSFT",
            "US.NVDA",
            "US.GOOG",
            "US.AMZN",
            "US.META",  # noqa: E501
            "US.TSLA",
            "HK.00700",
            "HK.09988",
            "US.AMD",
            "US.INTC",
        ]

        # Redis ZSET Key 存储所有显著的交易，按时间排序
        MARQUEE_KEY = "quant:insider_marquee"
        # Redis Hash Key 用于事务去重 (transaction_hash -> timestamp)
        DEDUP_KEY = "quant:insider_dedup"

        while True:
            # 轮询间隔：例如 5 分钟刷新一次，拉取一次数据并入库
            await asyncio.sleep(300)
            try:
                print(f"🔄 [Finnhub Daemon] 正在刷新 {len(MAJOR_TICKERS)} 个核心标的的高管内幕交易...")  # noqa: E501

                new_transactions_count = 0
                for ticker in MAJOR_TICKERS:
                    # 调用现有的 get_insider_transactions 方法，它自带缓存和 Finnhub 格式转换  # noqa: E501
                    res = await self.get_insider_transactions(ticker=ticker, limit=5)

                    if res.get("status") == "success" and res.get("data"):
                        transactions = res.get("data", [])

                        for tx in transactions:
                            # 计算交易金额，用于筛选显著交易
                            transaction_value = abs(tx.get("change", 0) * tx.get("transaction_price", 0))  # noqa: E501

                            # 💡 过滤条件：仅关注交易金额大于 $100,000 的大额交易，或者股数大于 10000 股的交易  # noqa: E501
                            if transaction_value >= 100000 or abs(tx.get("change", 0)) >= 10000:  # noqa: E501
                                # 生成唯一的交易哈希值，防止重复
                                tx_hash_data = {
                                    "ticker": ticker,
                                    "date": tx.get("date"),
                                    "name": tx.get("name"),
                                    "change": tx.get("change"),
                                    "price": tx.get("transaction_price"),
                                }
                                tx_hash = hashlib.md5(
                                    json.dumps(tx_hash_data, sort_keys=True).encode("utf-8")
                                ).hexdigest()  # noqa: E501

                                # 确保是今天或最近的交易
                                tx_date_str = tx.get("date", "")
                                if not tx_date_str:
                                    continue  # noqa: E701
                                try:
                                    tx_date = datetime.strptime(tx_date_str, "%Y-%m-%d").date()  # noqa: E501
                                    if (datetime.now().date() - tx_date).days > 3:  # 只保留最近3天的交易  # noqa: E501
                                        continue
                                    # 💡 修复：将 date 对象转换为 datetime 对象以获取 timestamp  # noqa: E501
                                    tx_datetime = datetime.combine(tx_date, datetime.min.time())  # noqa: E501
                                    tx_timestamp = tx_datetime.timestamp()
                                except ValueError:
                                    continue  # noqa: E701

                                # 使用 Redis set NX (Not Exists) 原子操作进行去重，确保每个交易只入库一次  # noqa: E501
                                is_new = await redis_client.set(
                                    f"{DEDUP_KEY}:{tx_hash}", "1", nx=True, ex=86400 * 7
                                )  # 7天去重周期  # noqa: E501
                                if is_new:
                                    # 将交易时间戳作为 ZSET 的 Score，便于按时间排序
                                    await redis_client.zadd(
                                        MARQUEE_KEY,
                                        {json.dumps(tx_hash_data): tx_timestamp},
                                    )  # noqa: E501
                                new_transactions_count += 1

                if new_transactions_count > 0:
                    print(
                        f"✨ [Finnhub Daemon] 检测到 {new_transactions_count} 条新的显著高管交易，已推送到跑马灯队列。"
                    )  # noqa: E501
                    # 限制 ZSET 队列大小，只保留最近 100 条大额交易
                    await redis_client.zremrangebyrank(MARQUEE_KEY, 0, -101)

            except Exception as e:
                print(f"❌ [Finnhub Daemon] 高管内幕交易跑马灯监控异常: {e}")


finnhub_service = FinnhubService()
