"""个股新闻与行情 Mixin"""

import asyncio
import json
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict

from backend.core.circuit_breaker import get_cooldown_seconds
from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry


class QuoteMixin:
    """个股新闻 + A股实时行情 + 历史K线"""

    @with_global_retry
    async def get_company_news(self, ticker: str) -> Dict[str, Any]:
        """
        获取港股或A股的个股新闻（短链接，Redis 缓存）
        数据来源: 东方财富 (AKShare)
        """
        # 🚨 熔断拦截：直接短路并交由上一级继续降级
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 数据源触发限流熔断，冷却中",
                "data": [],
            }  # noqa: E501

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

        try:
            import re

            import akshare as ak

            # 💡 拦截板块指数代码 (如 HK.BK1118)，防止正则提取数字后发生串台
            if "BK" in ticker.upper():
                return {
                    "status": "warning",
                    "message": f"[{ticker}] 为板块指数，不适用个股新闻接口",
                    "data": [],
                }  # noqa: E501

            # 💡 针对港股，东方财富 A 股新闻接口经常因页面结构变化抛出正则解析异常 (Invalid escape sequence)  # noqa: E501
            # 因此在这里直接将其短路，降级交由雅虎财经获取港股新闻
            if "HK" in ticker.upper() or (ticker.isdigit() and len(ticker) == 5):
                from backend.services.finnhub_service import finnhub_service

                yf_sym = ticker
                if yf_sym.startswith("HK."):
                    yf_sym = f"{yf_sym[3:]}.HK"
                elif yf_sym.isdigit():
                    yf_sym = f"{yf_sym}.HK"

                yahoo_news = await finnhub_service._fallback_yahoo_news(yf_sym)

                result = {
                    "status": "success",
                    "data": yahoo_news[:30],
                    "source": "yahoo_fallback",
                }  # noqa: E501
                self._error_count = 0
                result["updated_at"] = datetime.now(timezone.utc).isoformat()

                if yahoo_news:
                    await redis_client.set(cache_key, json.dumps(result), ex=86400)
                else:
                    await redis_client.set(cache_key, json.dumps(result), ex=60)
                return result

            # 提取纯数字代码，例如从 "SH.600519" 中提取 "600519"
            match = re.search(r"\d+", ticker)
            if not match:
                raise ValueError(f"无法从代码 {ticker} 提取纯数字代码以获取新闻")
            symbol = match.group()

            # 💡 强制补齐位数：A 股必须为 6 位纯数字
            if "SH" in ticker.upper() or "SZ" in ticker.upper():
                symbol = symbol.zfill(6)

            # stock_news_em 返回 columns: ['关键词', '新闻标题', '新闻内容', '发布时间', '文章来源', '新闻链接']  # noqa: E501
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                df = await asyncio.to_thread(ak.stock_news_em, symbol=symbol)
            if df is None or df.empty:
                raise ValueError(f"获取到的 {ticker} 新闻数据为空")

            if "发布时间" in df.columns:
                df = df.sort_values(by="发布时间", ascending=False)

            news_list = []
            for _, row in df.head(30).iterrows():  # 截取前 30 条作为热缓存
                pub_time = str(row.get("发布时间", ""))

                # 兼容格式，将 datetime 转换为 UNIX 时间戳
                try:
                    dt = datetime.strptime(pub_time, "%Y-%m-%d %H:%M:%S")
                    ts = dt.replace(tzinfo=timezone.utc).timestamp()
                except Exception:
                    ts = datetime.now().timestamp()

                news_list.append(
                    {
                        "datetime": ts,
                        "date": pub_time,
                        "headline": str(row.get("新闻标题", "")),
                        "summary": str(row.get("新闻内容", "")),
                        "url": str(row.get("新闻链接", "")),
                        "source": str(row.get("文章来源", "东方财富")),
                    }
                )

            result = {"status": "success", "data": news_list, "source": "akshare"}
            self._error_count = 0  # 成功则清零错误计数
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] 个股新闻获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发个股新闻熔断休眠 60 秒！")  # noqa: E501
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()

            result = {
                "status": "error",
                "message": f"AKShare 个股新闻获取失败: {e}",
                "data": [],
            }  # noqa: E501

        result["updated_at"] = datetime.now(timezone.utc).isoformat()

        if result.get("status") == "success" and result.get("data"):
            ttl = 86400 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)

        return result

    @with_global_retry
    async def get_stock_quote(self, ticker: str) -> Dict[str, Any]:
        """获取 A 股个股实时行情兜底 (基于东方财富)"""
        # 🚨 熔断拦截
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 行情接口熔断中，直接降级雅虎财经",
            }  # noqa: E501

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

        import re

        match = re.search(r"\d+", ticker)
        if not match:
            return {"status": "error", "message": "无效的 A 股代码"}
        symbol = match.group().zfill(6)

        try:
            import akshare as ak

            # 为保证实时性，获取日线最近一条数据（包含今日盘中实时变动）
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                df = await asyncio.to_thread(ak.stock_zh_a_hist, symbol=symbol, period="daily", adjust="qfq")  # noqa: E501

            if df is None or df.empty:
                raise ValueError("获取到的个股行情为空")

            latest = df.iloc[-1]
            prev_close = float(df.iloc[-2]["收盘"]) if len(df) > 1 else float(latest["开盘"])  # noqa: E501
            last_price = float(latest["收盘"])
            change = last_price - prev_close
            change_pct = (change / prev_close) * 100 if prev_close > 0 else 0.0

            vol = float(latest["成交量"]) * 100  # AKShare 返回单位为手，转化为股
            result = {
                "status": "success",
                "data": {
                    "ticker": ticker,
                    "last_price": last_price,
                    "open": float(latest["开盘"]),
                    "high": float(latest["最高"]),
                    "low": float(latest["最低"]),
                    "prev_close": prev_close,
                    "volume": vol,
                    "turnover": float(latest["成交额"]),
                    "change_val": change,
                    "change_pct": change_pct,
                    "amplitude": float(latest.get("振幅", 0.0)),
                    "volume_str": f"{vol / 1_000_000:.2f}M" if vol > 1_000_000 else f"{vol / 1_000:.2f}K",  # noqa: E501
                },
                "source": "akshare_fallback",
            }
            # 短效缓存防穿透
            ttl = 10 + random.randint(1, 5)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            self._error_count = 0
            return result
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] A 股行情获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发实时行情熔断休眠 60 秒！")  # noqa: E501
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()

            return {"status": "error", "message": f"行情异常: {e}"}

    @with_global_retry
    async def get_stock_history(self, ticker: str, num: int = 60) -> Dict[str, Any]:
        """获取 A 股个股历史 K 线兜底 (基于东方财富前复权)"""
        # 🚨 熔断拦截
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "error",
                "message": "AKShare 历史K线接口熔断中，直接降级雅虎财经",
            }  # noqa: E501

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

        import re

        match = re.search(r"\d+", ticker)
        if not match:
            return {"status": "error", "message": "无效的 A 股代码"}
        symbol = match.group().zfill(6)

        try:
            import akshare as ak

            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                df = await asyncio.to_thread(ak.stock_zh_a_hist, symbol=symbol, period="daily", adjust="qfq")  # noqa: E501

            if df is None or df.empty:
                raise ValueError("获取到的 K 线为空")

            df = df.tail(num)
            data_list = [
                {
                    "time": str(row["日期"]) + " 00:00:00",
                    "open": float(row["开盘"]),
                    "high": float(row["最高"]),
                    "low": float(row["最低"]),
                    "close": float(row["收盘"]),
                    "volume": float(row["成交量"]) * 100,
                }
                for _, row in df.iterrows()
            ]  # noqa: E501
            self._error_count = 0

            result = {
                "status": "success",
                "data": data_list,
                "source": "akshare_fallback",
            }  # noqa: E501
            ttl = 10 + random.randint(1, 5)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
        except Exception as e:
            self._error_count += 1
            print(f"⚠️ [AKShare] A 股历史 K 线获取失败: {e}")
            if self._error_count >= self._max_errors:
                print(f"🚨 [AKShare] 连续报错 {self._error_count} 次，触发 K 线接口熔断休眠 60 秒！")  # noqa: E501
                self._circuit_breaker_until = time.time() + get_cooldown_seconds()

            return {"status": "error", "message": f"K线异常: {e}"}
