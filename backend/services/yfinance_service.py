import asyncio
import concurrent.futures
import json
import os
import random
import re
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple, cast

import pandas as pd
import requests
import yfinance as yf

from backend.services.notification_service import notification_service

# llm_service 改为懒加载，仅在 macro_data_daemon 中通过 self.llm_service 访问
# 构造函数接受 llm_service_instance 参数，测试时可注入 mock 对象


def format_yf_ticker(ticker: str) -> str:
    yf_ticker = ticker.upper().replace("US.", "")
    index_map = {
        "HSI": "^HSI",
        "HK.800000": "^HSI",
        "HK.HSI": "^HSI",
        "HSTECH": "800700.HK",
        "HK.800700": "800700.HK",
        "SPX": "^GSPC",
        "IXIC": "^IXIC",
        "DJI": "^DJI",
        "VIX": "^VIX",
        "SSEC": "000001.SS",
        "000001.SH": "000001.SS",
        "CSI300": "000300.SS",
        "399300.SZ": "399300.SZ",
        "399001.SZ": "399001.SZ",
        "TSMC": "TSM",
        "N225": "^N225",
        "DX-Y": "DX-Y.NYB",
        "TNX": "^TNX",
        "GC=F": "GC=F",
        "JGB10Y": "^JN09T",
        "USDCNH": "USDCNH=X",
        "BTC": "BTC-USD",
        "CL=F": "CL=F",
    }
    if yf_ticker in index_map:
        return index_map[yf_ticker]

    if yf_ticker.endswith(".HK") or yf_ticker.startswith("HK."):
        code = yf_ticker.replace(".HK", "").replace("HK.", "")
        yf_ticker = f"{code.lstrip('0').zfill(4)}.HK" if code.isdigit() else f"{code}.HK"  # noqa: E501
    elif yf_ticker.startswith("SH."):
        yf_ticker = yf_ticker.replace("SH.", "") + ".SS"
    elif yf_ticker.endswith(".SH"):
        yf_ticker = yf_ticker.replace(".SH", ".SS")
    elif yf_ticker.startswith("SZ."):
        yf_ticker = yf_ticker.replace("SZ.", "") + ".SZ"
    elif yf_ticker.startswith("JP."):
        yf_ticker = yf_ticker.replace("JP.", "") + ".T"  # 东京交易所后缀
    elif yf_ticker.startswith("SG."):
        yf_ticker = yf_ticker.replace("SG.", "") + ".SI"  # 新加坡交易所后缀
    elif yf_ticker.startswith("UK.") or yf_ticker.startswith("LSE."):
        yf_ticker = yf_ticker.replace("UK.", "").replace("LSE.", "") + ".L"  # 伦敦交易所后缀  # noqa: E501

    return yf_ticker


class RateLimitedSession(requests.Session):
    """
    带有线程安全限流器的 requests.Session。
    防止 yfinance 在开启并发下载或大批量请求时被 Yahoo 封锁 (429)。
    """

    def __init__(self, max_requests: int = 1, per_seconds: float = 2.0):
        super().__init__()
        self.max_requests = max_requests  # 1 request
        self.per_seconds = per_seconds
        self._request_times = deque()
        self._rl_lock = threading.Lock()

    def request(self, method, url, *args, **kwargs):
        # 🚨 致命遗漏修复：强制注入请求超时限制。
        # yfinance 内部大量网络请求未显式配置 timeout。若雅虎服务器假死，
        # 请求会永久挂起，从而耗尽 FastAPI 默认的 asyncio.to_thread 线程池导致整个网关死锁！  # noqa: E501
        kwargs.setdefault("timeout", 15.0)

        sleep_time = 0.0
        with self._rl_lock:
            now = time.time()
            while self._request_times and now > self._request_times[0] + self.per_seconds:  # noqa: E501
                self._request_times.popleft()

            if len(self._request_times) >= self.max_requests:
                # 严格按照先进先出漏桶控制，保障每 per_seconds 内最多执行 max_requests 次  # noqa: E501
                earliest_allowed = self._request_times[-self.max_requests] + self.per_seconds  # noqa: E501
                sleep_time = earliest_allowed - now
                if sleep_time < 0:
                    sleep_time = 0

            self._request_times.append(now + sleep_time)

        if sleep_time > 0:
            time.sleep(sleep_time)

        from backend.core.logger import logger
        from backend.core.middleware import EXTERNAL_API_COUNT, EXTERNAL_API_LATENCY

        start_t = time.perf_counter()
        try:
            res = super().request(method, url, *args, **kwargs)
            process_time = time.perf_counter() - start_t
            EXTERNAL_API_COUNT.labels(service_name="yfinance", method=method, http_status=res.status_code).inc()  # noqa: E501
            EXTERNAL_API_LATENCY.labels(service_name="yfinance", method=method).observe(process_time)  # noqa: E501
            if process_time > 3.0:
                logger.warning(f"🐢 [Slow Egress API] yfinance ({method} {url}) 耗时: {process_time:.2f}s")  # noqa: E501
            return res
        except Exception as e:
            process_time = time.perf_counter() - start_t
            EXTERNAL_API_COUNT.labels(service_name="yfinance", method=method, http_status=500).inc()  # noqa: E501
            EXTERNAL_API_LATENCY.labels(service_name="yfinance", method=method).observe(process_time)  # noqa: E501
            raise e


# 💡 内存安全防御：缓存容量上限 + TTL 清理
_YF_CACHE_MAX_SIZE = 500  # 最多缓存 500 个条目
_YF_CACHE_TTL = 600  # 缓存 TTL 10 分钟
_YF_ERROR_CACHE_TTL = 300  # 错误黑名单 TTL 5 分钟


class YFinanceService:
    def __init__(self, llm_service_instance=None):
        self._cache = {}  # { cache_key: (timestamp, data) }
        self._error_cache = {}  # { cache_key: timestamp } 黑名单缓存
        self._req_lock = asyncio.Lock()
        self._last_req_time = 0.0
        self._circuit_breaker_until = 0.0  # 全局熔断器：记录熔断结束的时间戳

        # llm_service 支持依赖注入：测试时可传入 mock，生产环境使用全局单例
        self._llm_service_override = llm_service_instance

        # 💡 微批处理队列机制 (Micro-batching Queue / DataLoader)
        self._batch_queue = {}
        self._batch_lock = asyncio.Lock()
        self._batch_dispatch_task = None

        # 💡 隔离线程池防死锁：YFinance 的限流机制包含同步的 time.sleep()。
        # 必须使用专属隔离的线程池，防止其休眠耗尽 FastAPI/asyncio 默认的全局 to_thread 线程池，导致整个网关瘫痪！  # noqa: E501
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="YFinanceWorker")  # noqa: E501

        self._init_session()

    def _evict_stale_cache(self):
        """内存安全防御：清理过期缓存，防止无界字典无限增长导致 OOM"""
        now = time.time()
        # 1. 清理主缓存：超过 TTL 的条目
        stale_keys = [k for k, (ts, _) in self._cache.items() if now - ts > _YF_CACHE_TTL]
        for k in stale_keys:
            del self._cache[k]
        # 2. 容量熔断：如果清理后仍超过上限，直接清空最旧的一半
        if len(self._cache) > _YF_CACHE_MAX_SIZE:
            sorted_keys = sorted(self._cache, key=lambda k: self._cache[k][0])
            for k in sorted_keys[: len(sorted_keys) // 2]:
                del self._cache[k]
        # 3. 清理错误黑名单：超过 TTL 的条目
        error_stale = [k for k, ts in self._error_cache.items() if now - ts > _YF_ERROR_CACHE_TTL]
        for k in error_stale:
            del self._error_cache[k]

    @property
    def llm_service(self):
        """懒加载 llm_service：优先使用注入的实例，否则导入全局单例"""
        if self._llm_service_override is not None:
            return self._llm_service_override
        from backend.services.llm_service import llm_service as real_llm_service

        return real_llm_service

    def _init_session(self):
        """初始化带有随机 User-Agent 的会话，防止长进程 Cookie 被封/过期"""
        # 💡 高并发安全修复：不再主动执行 self.session.close()
        # 若并发时某个协程触发 429 导致重置，强行 close 会切断其他线程正活跃的 TCP Socket 引发大规模报错。  # noqa: E501
        # 直接重新赋值让旧对象脱离引用链，交由 Python GC 在安全时刻自动清理底层连接池，实现无损平滑轮换。  # noqa: E501

        # 💡 注入定制化 Session，放宽速率至 2次/秒 提高吞吐量
        self.session = RateLimitedSession(max_requests=2, per_seconds=1.0)
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",  # noqa: E501
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",  # noqa: E501
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",  # noqa: E501
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",  # noqa: E501
        ]
        self.session.headers.update({"User-Agent": random.choice(user_agents)})

    def close(self):
        """安全关闭 requests.Session 释放连接池"""
        if hasattr(self, "session") and self.session:
            self.session.close()
        if hasattr(self, "_executor") and self._executor:
            self._executor.shutdown(wait=False)

    def get_health_status(self) -> Dict[str, Any]:
        """获取当前雅虎财经接口的熔断与健康状态"""
        now = time.time()
        is_open = now < self._circuit_breaker_until
        return {
            "name": "Yahoo Finance",
            "status": "circuit_open" if is_open else "healthy",
            "cooldown_remaining": max(0, int(self._circuit_breaker_until - now)) if is_open else 0,  # noqa: E501
            "message": "触发 429 限流熔断中" if is_open else "正常",
        }

    async def fetch_yf_data(
        self, ticker: str, fetch_type: str, ttl: int, persist: bool = False, **kwargs
    ) -> Tuple[bool, Any, str]:  # noqa: E501
        if os.getenv("QUANT_ENV") == "development" and yf is None:
            return False, None, "development_mock"
        if yf is None:
            return False, None, "环境缺失 yfinance 依赖"

        yf_ticker = format_yf_ticker(ticker)

        # 🚨 全局熔断拦截：如果当前雅虎 IP 被封处于冷却期，直接短路所有网络请求
        if time.time() < self._circuit_breaker_until:
            return False, None, "限流冷却中：雅虎财经数据源全局熔断保护中，正在休眠冷却"

        cache_key = f"yf_{fetch_type}_{yf_ticker}" + (
            "_" + "_".join([f"{k}_{v}" for k, v in kwargs.items()]) if kwargs else ""
        )  # noqa: E501

        now = time.time()

        # 黑名单拦截：如果该请求在最近 5 分钟（300秒）内曾经失败过，直接拦截，拒绝发起真实网络请求  # noqa: E501
        if cache_key in self._error_cache:
            if now - self._error_cache[cache_key] < 300:
                return (
                    False,
                    None,
                    f"数据源限流冷却中：{yf_ticker} 请求过于频繁，请等待几分钟后重试",
                )  # noqa: E501
            else:
                del self._error_cache[cache_key]  # 过期则移除黑名单，给它一次重新做人的机会  # noqa: E501

        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if now - ts < ttl:
                if not (fetch_type == "history" and getattr(data, "empty", False)) and not (
                    fetch_type == "info" and len(data) <= 1
                ):  # noqa: E501
                    return True, data, ""

        try:

            def _do_fetch():
                # 捕获 yfinance 多线程下载时产生的隐式异常
                yf_shared = getattr(yf, "shared", None)
                if yf_shared is not None:
                    getattr(yf_shared, "_ERRORS", {}).clear()

                kwargs.setdefault("progress", False)
                kwargs.setdefault("session", self.session)
                kwargs.setdefault("threads", False)  # type: ignore # 🚨 核心：必须完全禁用 yf 的隐式多线程，防止与 RateLimitedSession 产生“线程炸弹”

                res = (
                    yf.Ticker(yf_ticker, session=self.session).info
                    if fetch_type == "info"
                    else yf.download(yf_ticker, **kwargs)
                )  # noqa: E501

                if yf_shared is not None:
                    errs = getattr(yf_shared, "_ERRORS", {})
                    if errs:
                        err_str = str(errs)
                        # 🚨 穿透拦截：只要 yfinance 报告了 429 限流，必须立刻抛出异常触发全局熔断，绝不能当做空数据处理！  # noqa: E501
                        if (
                            "429" in err_str
                            or "Rate limit" in err_str
                            or "Too Many Requests" in err_str
                            or "YFRateLimitError" in err_str
                        ):  # noqa: E501
                            raise Exception(f"YFRateLimitError: {err_str}")
                        elif yf_ticker in errs:
                            raise Exception(errs[yf_ticker])
                return res

            # 内部拦截器：将发往雅虎的请求通过异步锁进行排队节流
            async def _rate_limited_fetch():
                if self._req_lock is None:
                    self._req_lock = asyncio.Lock()  # 懒加载以绑定到当前协程的事件循环
                async with self._req_lock:
                    # 底层 Session 已有严格的 HTTP 线程锁限流，此处适度放宽异步锁，让并发请求交由 Session 高效排队  # noqa: E501
                    dynamic_interval = random.uniform(0.5, 1.5)
                    elapsed = time.time() - self._last_req_time
                    if elapsed < dynamic_interval:
                        await asyncio.sleep(dynamic_interval - elapsed)
                    self._last_req_time = time.time()

                # 🚨 致命缺陷修复：将耗时的 to_thread 网络 IO 移出异步锁！
                # 否则一旦某个请求拥堵，该锁将被死死霸占 15 秒以上，直接卡死所有其他正在排队获取行情的协程！  # noqa: E501
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self._executor, _do_fetch)

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    data = await _rate_limited_fetch()

                    # 判断是否软限流
                    is_soft_limited = False
                    if fetch_type == "history" and getattr(data, "empty", True):
                        is_soft_limited = True
                    elif fetch_type == "info" and isinstance(data, dict) and len(data) <= 1:  # noqa: E501
                        is_soft_limited = True

                    if not is_soft_limited:
                        self._evict_stale_cache()
                        self._cache[cache_key] = (time.time(), data)
                        self._error_cache.pop(cache_key, None)  # 成功获取则移除黑名单
                        return True, data, ""

                    print(
                        f"⚠️ [YFinance API] 第 {attempt + 1} 次获取到空数据 (疑似软限流/Cookie失效) -> Ticker: {yf_ticker}"
                    )  # noqa: E501
                except Exception as loop_e:
                    err_str = str(loop_e)
                    print(f"⚠️ [YFinance API] 第 {attempt + 1} 次请求异常 -> Ticker: {yf_ticker} | Error: {err_str}")  # noqa: E501
                    if (
                        "429" in err_str
                        or "Rate limit" in err_str
                        or "Too Many Requests" in err_str
                        or "YFRateLimitError" in err_str
                    ):  # noqa: E501
                        print("🚨 [YFinance] 触发全局限流熔断！所有雅虎请求将强制休眠 60 秒以释放压力")  # noqa: E501
                        self._circuit_breaker_until = time.time() + 60.0
                        return (
                            False,
                            None,
                            "限流冷却中：yfinance 触发了 429 限流保护。已开启全局熔断，请等待 60 秒后重试。",
                        )  # noqa: E501

                if attempt < max_retries - 1:
                    # 指数退避 + 随机抖动
                    backoff = random.uniform(2.0, 5.0) * (2**attempt)
                    print(f"🔄 [YFinance API] 准备第 {attempt + 2} 次重试，重置 Session 并退避休眠 {backoff:.1f} 秒...")  # noqa: E501
                    await asyncio.sleep(backoff)
                    self._init_session()
                    kwargs["session"] = self.session

            self._error_cache[cache_key] = time.time()
            return (
                False,
                None,
                f"重试 {max_retries} 次后仍然失败，获取 {yf_ticker} 数据无效",
            )  # noqa: E501
        except Exception as e:
            self._error_cache[cache_key] = time.time()  # 记录进黑名单
            err_str = str(e)
            print(f"⚠️ [YFinance] 外层兜底异常 | ticker: {yf_ticker} | fetch_type: {fetch_type} | error: {err_str}")  # noqa: E501
            return False, None, f"yfinance 未知系统异常: {err_str}"

    async def get_batched_quote(self, ticker: str, req_type: str = "quote", **kwargs) -> Dict[str, Any]:  # noqa: E501
        """
        💡 革命性优化：基于微批处理 (Micro-batching) 的异步数据加载器。
        支持动态混入 "quote" (实时行情) 和 "tech" (技术指标) 类型的合并请求。
        """
        yf_ticker = format_yf_ticker(ticker)

        # 💡 1. 检查全局熔断器
        if time.time() < self._circuit_breaker_until:
            return {"status": "error", "message": "雅虎财经数据源全局熔断保护中"}

        # 💡 2. 检查 L1 缓存 (按请求类型和参数强隔离)
        kwargs_str = (
            "_".join([f"{k}_{str(v).replace(' ', '')}" for k, v in sorted(kwargs.items())]) if kwargs else "default"
        )  # noqa: E501
        cache_key = f"yf_batch_{req_type}_{yf_ticker}_{kwargs_str}"

        now = time.time()
        # 行情缓存 120 秒防限流，技术指标运算重，缓存 1 小时
        ttl = 120.0 if req_type == "quote" else 3600.0
        if cache_key in self._cache and (now - self._cache[cache_key][0] < ttl):
            return self._cache[cache_key][1]

        # 💡 3. 检查黑名单 (5分钟冷却，防止退市/错误标的引发重复超时卡顿)
        if cache_key in self._error_cache and (now - self._error_cache[cache_key] < 300.0):  # noqa: E501
            return {"status": "error", "message": f"{ticker} 数据拉取频繁失败，冷却中"}

        loop = asyncio.get_running_loop()
        # 交给业务方一个“取餐号” (Future)，业务方会原地 await 等待数据
        fut = loop.create_future()

        async with self._batch_lock:
            if yf_ticker not in self._batch_queue:
                self._batch_queue[yf_ticker] = []
            self._batch_queue[yf_ticker].append(
                {
                    "fut": fut,
                    "req_type": req_type,
                    "kwargs": kwargs,
                    "cache_key": cache_key,
                }
            )  # noqa: E501

            # 若是队列中的第一个请求，则启动一个 1 秒倒计时的发车任务
            if not self._batch_dispatch_task or self._batch_dispatch_task.done():
                self._batch_dispatch_task = asyncio.create_task(self._dispatch_batch_quotes())  # noqa: E501

        try:
            # 业务方带着取餐号在此挂起等待 (设置 15 秒超时防止死锁)
            return await asyncio.wait_for(fut, timeout=15.0)
        except asyncio.TimeoutError:
            return {"status": "error", "message": "批量请求排队或执行超时"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def _dispatch_batch_quotes(self):
        """真正的批量拉取与回调分发逻辑 (Consumer)"""
        await asyncio.sleep(1.0)  # 收集 1 秒内的所有离散请求 (微批处理时间窗口)

        async with self._batch_lock:
            batch = self._batch_queue
            self._batch_queue = {}  # 清空队列，迎接下一波

        if not batch:
            return

        tickers = list(batch.keys())
        tickers_str = " ".join(tickers)

        # 💡 动态决策拉取周期：只要队列中混入了任意技术指标请求，自动将全局历史拉长至半年 (6mo)  # noqa: E501
        needs_tech = any(req["req_type"] == "tech" for reqs in batch.values() for req in reqs)  # noqa: E501
        period = "6mo" if needs_tech else "5d"

        def _do_batch_fetch():
            yf_shared = getattr(yf, "shared", None)
            if yf_shared is not None:
                getattr(yf_shared, "_ERRORS", {}).clear()

            res = yf.download(
                tickers_str,
                period=period,
                interval="1d",
                group_by="ticker",
                threads=False,  # type: ignore # 🚨 核心：必须禁用，防止 yf 在后台衍生大量线程与限流器互相锁死
                progress=False,
                session=self.session,
            )

            if yf_shared is not None:
                errs = getattr(yf_shared, "_ERRORS", {})
                if errs:
                    err_str = str(errs)
                    if (
                        "429" in err_str
                        or "Rate limit" in err_str
                        or "Too Many Requests" in err_str
                        or "YFRateLimitError" in err_str
                    ):  # noqa: E501
                        raise Exception(f"YFRateLimitError: {err_str}")
            return res

        try:
            df = None
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    loop = asyncio.get_running_loop()
                    df = await loop.run_in_executor(self._executor, _do_batch_fetch)
                    if df is not None and not df.empty:
                        break
                    print(f"⚠️ [YF Batcher] 第 {attempt + 1} 次获取到空数据 (疑似软限流/Cookie失效)")  # noqa: E501
                except Exception as loop_e:
                    err_str = str(loop_e)
                    print(f"⚠️ [YF Batcher] 第 {attempt + 1} 次请求异常: {err_str}")
                    if (
                        "429" in err_str
                        or "Rate limit" in err_str
                        or "Too Many Requests" in err_str
                        or "YFRateLimitError" in err_str
                    ):  # noqa: E501
                        print("🚨 [YF Batcher] 触发全局限流熔断！所有雅虎请求将强制休眠 60 秒以释放压力")  # noqa: E501
                        self._circuit_breaker_until = time.time() + 60.0
                        df = None
                        break

                if attempt < max_retries - 1:
                    backoff = random.uniform(2.0, 5.0) * (2**attempt)
                    print(f"🔄 [YF Batcher] 准备第 {attempt + 2} 次重试，重置 Session 并退避休眠 {backoff:.1f} 秒...")  # noqa: E501
                    await asyncio.sleep(backoff)
                    self._init_session()

            # 💡 性能修复：将耗时的 Pandas 数据集切片操作 (df.xs) 推入物理线程池防阻塞
            def _slice_all(local_df: Optional[pd.DataFrame]):
                results = {}
                for t in batch.keys():
                    try:
                        if local_df is None or not hasattr(local_df, "empty") or local_df.empty:  # noqa: E501
                            results[t] = ValueError("返回空数据或连续重试失败")
                            continue
                        if isinstance(local_df.columns, pd.MultiIndex):
                            if t in local_df.columns.levels[0] or t in local_df:
                                ticker_df = local_df[t].dropna(how="all")
                            elif "Close" in local_df:
                                ticker_df = (
                                    local_df.xs(t, axis=1, level=1).dropna(how="all")
                                    if t in local_df.columns.get_level_values(1)
                                    else pd.DataFrame()
                                )  # noqa: E501
                            else:
                                ticker_df = pd.DataFrame()
                        else:
                            ticker_df = local_df.dropna(how="all")

                        if ticker_df.empty or len(ticker_df) == 0:
                            results[t] = ValueError(f"未获取到 {t} 的数据")
                        else:
                            results[t] = ticker_df
                    except Exception as e:
                        results[t] = e
                return results

            loop = asyncio.get_running_loop()
            sliced_results = await loop.run_in_executor(self._executor, _slice_all, df)

            for t, reqs in batch.items():
                try:
                    ticker_res = sliced_results.get(t)
                    if isinstance(ticker_res, Exception):
                        raise ticker_res
                    ticker_df = ticker_res

                    if ticker_df is None or not hasattr(ticker_df, "empty") or ticker_df.empty:  # noqa: E501
                        raise ValueError("数据切片结果为空或非法类型")

                    # 💡 遍历分发给挂起的不同请求类型
                    for req in reqs:
                        fut = req["fut"]
                        if fut.done():
                            continue  # noqa: E701

                        res = None
                        if req["req_type"] == "quote":
                            if "Close" not in ticker_df.columns:
                                raise ValueError("返回数据缺失 Close 列")
                            last_price = float(ticker_df["Close"].iloc[-1])
                            prev_close = (
                                float(ticker_df["Close"].iloc[-2])
                                if len(ticker_df) > 1
                                else float(ticker_df["Open"].iloc[-1])
                            )  # noqa: E501
                            change_pct = ((last_price - prev_close) / prev_close) * 100 if prev_close else 0.0  # noqa: E501
                            res = {
                                "status": "success",
                                "ticker": t,
                                "last_price": round(last_price, 4),
                                "change_pct": f"{change_pct:+.2f}%",
                                "source": "yfinance_batch",
                            }  # noqa: E501
                        elif req["req_type"] == "tech":
                            # 0 网络延迟回调！直接将切片好的 DataFrame 数据喂给技术面计算引擎  # noqa: E501
                            res = await self.get_tech_indicators(
                                ticker=t,
                                pre_fetched_df=cast(pd.DataFrame, ticker_df),
                                **req["kwargs"],
                            )  # noqa: E501

                        # 结果缓存与黑名单维护
                        if res and res.get("status") == "success":
                            self._evict_stale_cache()
                            self._cache[req["cache_key"]] = (time.time(), res)
                            self._error_cache.pop(req["cache_key"], None)
                        else:
                            if not res:
                                res = {"status": "error", "message": "处理失败"}  # noqa: E701
                            self._error_cache[req["cache_key"]] = time.time()

                        fut.set_result(res)
                except Exception as e:
                    print(f"⚠️ [YF Batcher] 数据切片 {t} 异常: {e}")
                    for req in reqs:
                        fut = req["fut"]
                        if not fut.done():
                            self._error_cache[req["cache_key"]] = time.time()
                            fut.set_result({"status": "error", "message": str(e)})
        except Exception as e:
            print(f"❌ [YF Batcher] 批量任务整体崩溃: {e}")
            for t, reqs in batch.items():
                for req in reqs:
                    fut = req["fut"]
                    if not fut.done():
                        self._error_cache[req["cache_key"]] = time.time()
                        fut.set_result({"status": "error", "message": str(e)})

    async def get_tech_indicators(
        self,
        ticker: str,
        ma_periods: Optional[List[int]] = None,
        rsi_period: int = 14,
        include_macd: bool = True,
        include_kdj: bool = True,
        atr_period: int = 14,
        stop_loss_multiplier: float = 2.0,
        take_profit_multiplier: float = 3.0,
        lookback_days: int = 1,
        bbands_period: int = 20,
        bbands_std_dev: float = 2.0,
        pre_fetched_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:  # noqa: E501
        if ma_periods is None:
            ma_periods = [10, 20]  # noqa: E701
        lookback_days = max(1, min(lookback_days, 30))

        df = pre_fetched_df
        if df is None:
            success, df, msg = await self.fetch_yf_data(
                ticker, "history", ttl=3600, persist=False, period="6mo", progress=False
            )  # noqa: E501
            if not success:
                # 将降级条件放宽，一旦获取失败就使用 mock 数据进行界面展示
                if msg == "development_mock" or "数据无效" in msg or "限流冷却" in msg:
                    fallback_data = self._mock_tech_data(
                        ticker,
                        ma_periods,
                        rsi_period,
                        include_macd,
                        atr_period,
                        stop_loss_multiplier,
                        take_profit_multiplier,
                        lookback_days,
                        bbands_period,
                        bbands_std_dev,
                    )  # noqa: E501
                    fallback_data["message"] = f"⚠️ {msg} (已自动降级为本地缓存/模拟数据)"  # noqa: E501
                    return fallback_data
                return {"status": "error", "message": msg}

        if df is None or df.empty:
            return {"status": "error", "message": "返回的数据为空，无法计算技术指标。"}

        try:
            # 💡 性能修复：将计算技术指标中极度耗时的 Pandas Rolling/Ewm 等强运算全部封装入线程池  # noqa: E501
            def _compute_tech(local_df: pd.DataFrame):
                if local_df is None or not hasattr(local_df, "empty") or local_df.empty:
                    raise ValueError("计算指标失败：输入数据为空或非法类型")
                open_series = cast(
                    pd.Series,
                    local_df["Open"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Open"],
                )  # noqa: E501
                close_series = cast(
                    pd.Series,
                    local_df["Close"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Close"],
                )  # noqa: E501
                high_series = cast(
                    pd.Series,
                    local_df["High"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["High"],
                )  # noqa: E501
                low_series = cast(
                    pd.Series,
                    local_df["Low"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Low"],
                )  # noqa: E501
                volume_series = cast(
                    pd.Series,
                    local_df["Volume"].squeeze() if isinstance(local_df.columns, pd.MultiIndex) else local_df["Volume"],
                )  # noqa: E501

                ma_dict = {p: close_series.rolling(window=p).mean() for p in ma_periods}
                rsi_series = None
                if rsi_period and rsi_period > 0:
                    delta = close_series.diff()
                    gain, loss = (
                        delta.where(delta > 0, 0.0),
                        -delta.where(delta < 0, 0.0),
                    )  # noqa: E501
                    rs = (
                        gain.ewm(alpha=1 / rsi_period, adjust=False).mean()
                        / loss.ewm(alpha=1 / rsi_period, adjust=False).mean()
                    )  # noqa: E501
                    rsi_series = 100 - (100 / (1 + rs))

                macd_hist, macd_line, signal_line = None, None, None
                if include_macd:
                    macd_line = (
                        close_series.ewm(span=12, adjust=False).mean() - close_series.ewm(span=26, adjust=False).mean()
                    )  # noqa: E501
                    signal_line = macd_line.ewm(span=9, adjust=False).mean()
                    macd_hist = macd_line - signal_line

                k_series, d_series, j_series = None, None, None
                if include_kdj:
                    # KDJ 标准算法 (N=9, M1=3, M2=3)
                    high_9 = high_series.rolling(window=9, min_periods=1).max()
                    low_9 = low_series.rolling(window=9, min_periods=1).min()
                    rsv = (close_series - low_9) / (high_9 - low_9) * 100
                    k_series = rsv.fillna(50).ewm(com=2, adjust=False).mean()  # com=2 等价于 alpha=1/3  # noqa: E501
                    d_series = k_series.ewm(com=2, adjust=False).mean()
                    j_series = 3 * k_series - 2 * d_series

                atr_series = None
                if atr_period and atr_period > 0:
                    tr = pd.concat(
                        [
                            high_series - low_series,
                            (high_series - close_series.shift(1)).abs(),
                            (low_series - close_series.shift(1)).abs(),
                        ],
                        axis=1,
                    ).max(axis=1)  # noqa: E501
                    atr_series = tr.ewm(alpha=1 / atr_period, adjust=False).mean()

                bb_middle, bb_upper, bb_lower = None, None, None
                if bbands_period and bbands_period > 0:
                    bb_middle = close_series.rolling(window=bbands_period).mean()
                    bb_std = close_series.rolling(window=bbands_period).std()
                    bb_upper, bb_lower = (
                        bb_middle + bbands_std_dev * bb_std,
                        bb_middle - bbands_std_dev * bb_std,
                    )  # noqa: E501

                trend_data = []
                for i in range(-lookback_days, 0):
                    if i < -len(close_series):
                        continue  # noqa: E701
                    day_res = {
                        "date": str(close_series.index[i].date()),
                        "open": round(float(open_series.iloc[i]), 2),
                        "high": round(float(high_series.iloc[i]), 2),
                        "low": round(float(low_series.iloc[i]), 2),
                        "close": round(float(close_series.iloc[i]), 2),
                        "volume": int(volume_series.iloc[i]),
                    }  # noqa: E501
                    for p in ma_periods:
                        day_res[f"MA_{p}"] = round(float(ma_dict[p].iloc[i]), 2)  # noqa: E501, E701
                    if rsi_series is not None:
                        day_res[f"RSI_{rsi_period}"] = round(float(rsi_series.iloc[i]), 2)  # noqa: E501, E701
                    if (
                        include_macd
                        and (macd_line is not None)
                        and (signal_line is not None)
                        and (macd_hist is not None)
                    ):
                        day_res.update(
                            {
                                "MACD_line": round(float(macd_line.iloc[i]), 3),
                                "MACD_signal": round(float(signal_line.iloc[i]), 3),
                                "MACD_hist": round(float(macd_hist.iloc[i]), 3),
                            }
                        )  # noqa: E501, E701
                    if include_kdj and (k_series is not None) and (d_series is not None) and (j_series is not None):
                        day_res.update(
                            {
                                "KDJ_K": round(float(k_series.iloc[i]), 2),
                                "KDJ_D": round(float(d_series.iloc[i]), 2),
                                "KDJ_J": round(float(j_series.iloc[i]), 2),
                            }
                        )  # noqa: E501, E701
                    if atr_series is not None:
                        curr_atr = float(atr_series.iloc[i])
                        day_res[f"ATR_{atr_period}"] = round(curr_atr, 3)
                        if ma_periods and day_res.get(f"MA_{ma_periods[0]}"):
                            day_res.update(
                                {
                                    "trailing_stop_loss": round(
                                        day_res[f"MA_{ma_periods[0]}"] - stop_loss_multiplier * curr_atr,
                                        2,
                                    ),
                                    "take_profit": round(
                                        day_res[f"MA_{ma_periods[0]}"] + take_profit_multiplier * curr_atr,
                                        2,
                                    ),
                                }
                            )  # noqa: E501, E701
                    if (bb_middle is not None) and (bb_upper is not None) and (bb_lower is not None):
                        day_res.update(
                            {
                                f"BB_middle_{bbands_period}": round(float(bb_middle.iloc[i]), 2),
                                f"BB_upper_{bbands_period}": round(float(bb_upper.iloc[i]), 2),
                                f"BB_lower_{bbands_period}": round(float(bb_lower.iloc[i]), 2),
                            }
                        )  # noqa: E501, E701

                    actions = []
                    if i - 1 >= -len(close_series):
                        if include_macd and macd_hist is not None:
                            actions.append("buy (MACD金叉)") if macd_hist.iloc[i] > 0 and macd_hist.iloc[
                                i - 1
                            ] <= 0 else actions.append("sell (MACD死叉)") if macd_hist.iloc[i] < 0 and macd_hist.iloc[
                                i - 1
                            ] >= 0 else None  # noqa: E501, E701
                        if include_kdj and (k_series is not None) and (d_series is not None):
                            actions.append("buy (KDJ金叉)") if k_series.iloc[i] > d_series.iloc[i] and k_series.iloc[
                                i - 1
                            ] <= d_series.iloc[i - 1] else actions.append("sell (KDJ死叉)") if k_series.iloc[
                                i
                            ] < d_series.iloc[i] and k_series.iloc[i - 1] >= d_series.iloc[i - 1] else None  # noqa: E501, E701
                        if ma_periods and len(ma_periods) >= 2:
                            actions.append(f"buy (MA{ma_periods[0]}上穿MA{ma_periods[1]})") if ma_dict[
                                ma_periods[0]
                            ].iloc[i] > ma_dict[ma_periods[1]].iloc[i] and ma_dict[ma_periods[0]].iloc[
                                i - 1
                            ] <= ma_dict[ma_periods[1]].iloc[i - 1] else actions.append(
                                f"sell (MA{ma_periods[0]}下穿MA{ma_periods[1]})"
                            ) if ma_dict[ma_periods[0]].iloc[i] < ma_dict[ma_periods[1]].iloc[i] and ma_dict[
                                ma_periods[0]
                            ].iloc[i - 1] >= ma_dict[ma_periods[1]].iloc[i - 1] else None  # noqa: E501, E701
                        if (bb_upper is not None) and (bb_lower is not None):
                            actions.append("buy (突破布林带上轨)") if close_series.iloc[i] > bb_upper.iloc[
                                i
                            ] and close_series.iloc[i - 1] <= bb_upper.iloc[i - 1] else actions.append(
                                "sell (跌破布林带下轨)"
                            ) if close_series.iloc[i] < bb_lower.iloc[i] and close_series.iloc[i - 1] >= bb_lower.iloc[
                                i - 1
                            ] else None  # noqa: E501, E701

                        # 💡 RSI 顶底背离探测逻辑 (简易高频版：过去 5 日对比，加入成交量辅助判断)  # noqa: E501
                        if rsi_series is not None and i - 5 >= -len(close_series):
                            vol_avg = volume_series.iloc[i - 5 : i].mean()
                            curr_vol = volume_series.iloc[i]

                            is_shrink = curr_vol < vol_avg * 0.8
                            is_expand = curr_vol > vol_avg * 1.2

                            # 底背离 (价格创新低，但 RSI 处在超卖区反弹)
                            if (
                                close_series.iloc[i] < close_series.iloc[i - 1]
                                and close_series.iloc[i] <= close_series.iloc[i - 5 : i].min()
                                and rsi_series.iloc[i] > rsi_series.iloc[i - 1]
                                and rsi_series.iloc[i] < 40
                            ):  # noqa: E501
                                if is_shrink:
                                    actions.append("buy (RSI底背离+缩量企稳)")
                                elif is_expand:
                                    actions.append("buy (RSI底背离+放量抢筹)")
                                else:
                                    actions.append("buy (疑似RSI底背离)")

                            # 顶背离 (价格创新高，但 RSI 处在超买区回落)
                            elif (
                                close_series.iloc[i] > close_series.iloc[i - 1]
                                and close_series.iloc[i] >= close_series.iloc[i - 5 : i].max()
                                and rsi_series.iloc[i] < rsi_series.iloc[i - 1]
                                and rsi_series.iloc[i] > 60
                            ):  # noqa: E501
                                if is_shrink:
                                    actions.append("sell (RSI顶背离+缩量滞涨)")
                                elif is_expand:
                                    actions.append("sell (RSI顶背离+放量出货)")
                                else:
                                    actions.append("sell (疑似RSI顶背离)")

                    day_res["action"] = " | ".join(actions) if actions else "hold"

                    # 💡 动态多空趋势综合评分 (0-100)
                    trend_score = 50.0
                    if ma_periods and len(ma_periods) >= 1:
                        ma_short = float(ma_dict[ma_periods[0]].iloc[i])
                        trend_score += 15 if close_series.iloc[i] > ma_short else -15

                        if len(ma_periods) >= 2:
                            ma_long = float(ma_dict[ma_periods[1]].iloc[i])
                            trend_score += 15 if ma_short > ma_long else -15

                        if atr_series is not None:
                            curr_atr = float(atr_series.iloc[i])
                            if curr_atr > 0:
                                # 计算价格偏离短均线的 ATR 倍数 (偏离 2 倍 ATR 即拉满 20 分)  # noqa: E501
                                atr_dist = (close_series.iloc[i] - ma_short) / curr_atr
                                trend_score += max(-20.0, min(20.0, atr_dist * 10))

                    # 💡 量价配合加分 (±10分)：放量上涨加分，放量下跌扣分
                    if i - 5 >= -len(close_series):
                        vol_avg = volume_series.iloc[i - 5 : i].mean()
                        curr_vol = volume_series.iloc[i]
                        # 当日成交量较过去 5 日均量放大 20% 即视为有效放量
                        if vol_avg > 0 and curr_vol > vol_avg * 1.2:
                            is_up = close_series.iloc[i] >= open_series.iloc[i]
                            trend_score += 10 if is_up else -10

                    day_res["trend_score"] = int(max(0, min(100, trend_score)))
                    trend_data.append(day_res)
                return {
                    "status": "success",
                    "data": {
                        "ticker": ticker,
                        "lookback_days": len(trend_data),
                        "trend": trend_data,
                    },
                }  # noqa: E501

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self._executor, _compute_tech, df)
        except Exception as e:
            return {"status": "error", "message": f"技术指标计算发生异常: {str(e)}"}

    def _mock_tech_data(
        self,
        ticker: str,
        ma_periods: List[int],
        rsi_period: int,
        include_macd: bool,
        atr_period: int,
        stop_loss_multiplier: float,
        take_profit_multiplier: float,
        lookback_days: int,
        bbands_period: int,
        bbands_std_dev: float,
    ) -> Dict[str, Any]:  # noqa: E501
        trend = []
        for i in range(lookback_days):
            day_data = {
                "date": f"2026-05-{20 + i}",
                "open": 144.5 + i,
                "high": 146.5 + i,
                "low": 143.5 + i,
                "close": 145.5 + i,
                "volume": 1200000 + i * 50000,
                "MA_10": 145.5,
                "MA_20": 142.1,
                "RSI_14": 65.4,
                "trend_score": 85,
                "action": "buy (MACD金叉)" if i == lookback_days - 1 else "hold",
            }  # noqa: E501
            if include_macd:
                day_data.update({"MACD_line": 1.25, "MACD_signal": 0.85, "MACD_hist": 0.40})  # noqa: E501, E701
            if atr_period:
                day_data.update(
                    {
                        f"ATR_{atr_period}": 5.94,
                        "trailing_stop_loss": round(145.5 - (stop_loss_multiplier * 5.94), 2),
                        "take_profit": round(145.5 + (take_profit_multiplier * 5.94), 2),
                    }
                )  # noqa: E501, E701
            if bbands_period:
                day_data.update(
                    {
                        f"BB_middle_{bbands_period}": 142.1,
                        f"BB_upper_{bbands_period}": 148.5,
                        f"BB_lower_{bbands_period}": 135.7,
                    }
                )  # noqa: E501, E701
            trend.append(day_data)
        return {
            "status": "success",
            "message": "未安装依赖，返回 Mock 数据",
            "data": {"ticker": ticker, "lookback_days": lookback_days, "trend": trend},
        }  # noqa: E501

    async def search_tickers(self, query: str) -> Dict[str, Any]:
        """代理调用雅虎财经的自动补全搜索接口，确保添加的标的是真实存在的"""
        import hashlib

        from backend.core.redis_client import redis_client

        if not query or len(query) > 50:
            return {"status": "success", "data": []}

        # 🚨 全局熔断拦截：搜索接口也要尊重 429 熔断状态
        if time.time() < self._circuit_breaker_until:
            return {
                "status": "warning",
                "message": "雅虎搜索接口全局限流熔断中，返回空列表",
                "data": [],
            }  # noqa: E501

        # 💡 修复特殊字符漏洞与超大 Key 耗尽内存的风险
        query_hash = hashlib.md5(query.strip().upper().encode("utf-8")).hexdigest()
        cache_key = f"quant:yf_search:{query_hash}"
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                return {"status": "success", "data": json.loads(cached)}
        except Exception:
            pass

        if not hasattr(self, "_search_locks"):
            self._search_locks = {}

        if cache_key not in self._search_locks:
            self._search_locks[cache_key] = asyncio.Lock()

        async with self._search_locks[cache_key]:
            try:
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return {"status": "success", "data": json.loads(cached_double)}
            except Exception:
                pass

            try:

                def _do_search():
                    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=8&newsCount=0"
                    res = self.session.get(url, timeout=5)
                    res.raise_for_status()
                    return res.json()

                loop = asyncio.get_running_loop()
                data = await loop.run_in_executor(self._executor, _do_search)
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

                # 💡 写入长效缓存 (7天有效 + 随机抖动防雪崩)，大幅缓解 API 限流压力
                if results:
                    try:
                        ttl = 604800 + random.randint(3600, 86400)
                        await redis_client.setex(cache_key, ttl, json.dumps(results))
                    except Exception:
                        pass

                return {"status": "success", "data": results}
            except Exception as e:
                print(f"⚠️ [YFinance] 搜索异常 | query: {query} | error: {e}")
                if "429" in str(e) or "Too Many Requests" in str(e):
                    print("🚨 [YFinance] 搜索触发限流熔断！接口将强制休眠 60 秒以释放压力")  # noqa: E501
                    self._circuit_breaker_until = time.time() + 60.0
                    return {
                        "status": "warning",
                        "message": "雅虎搜索接口触发限流，返回空列表",
                        "data": [],
                    }  # noqa: E501
                return {"status": "error", "message": f"搜索异常: {str(e)}"}

    async def macro_data_daemon(self) -> None:
        """后台守护进程：定时批量拉取宏观指标，彻底解决 YFinance 429 封控"""
        from backend.core.redis_client import redis_client

        # 需要高频守护的全球宏观指标与大盘代码 (严格对齐数据中心面板的 12 大资产)
        tickers = [
            "^GSPC",
            "^IXIC",
            "^HSI",
            "^TNX",
            "JPY=X",
            "DX-Y.NYB",
            "CNH=X",
            "BTC-USD",
            "GC=F",
            "CL=F",
            "^VIX",
            "^N225",
            "HG=F",
            "EURUSD=X",
            "GBPUSD=X",
            "3067.HK",
            "ES=F",
            "NQ=F",
            "XLK",
            "XLF",
            "XLE",
            "KWEB",
            "ETH-USD",
        ]
        tickers_str = " ".join(tickers)

        print("🚀 [YF Daemon] 启动宏观数据后台批量拉取任务...")

        base_interval = 120  # 常规休眠间隔拉长至 120 秒，彻底防范 429
        last_minute_prices = {}  # 💡 新增：记录上一分钟的价格基准，用于防范闪崩与暴涨
        last_summary_date = None  # 💡 新增：记录最后一次发送收盘报告的日期

        while True:
            # 💡 分布式锁：只允许集群中唯一一台节点 (Leader) 发起拉取，防止 N 台机器同时请求打爆雅虎限流  # noqa: E501
            lock_key = f"quant:lock:yf_daemon:{int(time.time() / base_interval)}"
            if not await redis_client.set(lock_key, "1", nx=True, ex=base_interval - 10):  # noqa: E501
                await asyncio.sleep(10)
                continue

            print(f"🔄 [YF Daemon] 启动新一轮宏观指标批量同步 (共 {len(tickers)} 个)...")  # noqa: E501
            try:

                def _do_batch_fetch():
                    yf_shared = getattr(yf, "shared", None)
                    if yf_shared is not None:
                        getattr(yf_shared, "_ERRORS", {}).clear()

                    res = yf.download(
                        tickers_str,
                        period="7d",
                        interval="1d",
                        group_by="ticker",
                        threads=False,
                        progress=False,
                        session=self.session,  # 🚨 核心：必须禁用多线程  # noqa: E501
                    )

                    if yf_shared is not None:
                        errs = getattr(yf_shared, "_ERRORS", {})
                        if errs:
                            err_str = str(errs)
                            if (
                                "429" in err_str
                                or "Rate limit" in err_str
                                or "Too Many Requests" in err_str
                                or "YFRateLimitError" in err_str
                            ):  # noqa: E501
                                raise Exception(f"YFRateLimitError: {err_str}")
                    return res

                df = None
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        loop = asyncio.get_running_loop()
                        df = await loop.run_in_executor(self._executor, _do_batch_fetch)
                        if df is not None and not df.empty:
                            break
                        print(f"  ⚠️ [YF Daemon] 第 {attempt + 1} 次获取到空数据 (疑似软限流/Cookie失效)")  # noqa: E501
                    except Exception as loop_e:
                        err_str = str(loop_e)
                        print(f"  ⚠️ [YF Daemon] 第 {attempt + 1} 次请求异常: {err_str}")
                        if (
                            "429" in err_str
                            or "Rate limit" in err_str
                            or "Too Many Requests" in err_str
                            or "YFRateLimitError" in err_str
                        ):  # noqa: E501
                            print("  🚨 [YF Daemon] 触发全局限流熔断！")
                            self._circuit_breaker_until = time.time() + 60.0
                            df = None
                            break

                    if attempt < max_retries - 1:
                        backoff = random.uniform(2.0, 5.0) * (2**attempt)
                        print(
                            f"  🔄 [YF Daemon] 准备第 {attempt + 2} 次重试，重置 Session 并退避休眠 {backoff:.1f} 秒..."
                        )  # noqa: E501
                        await asyncio.sleep(backoff)
                        self._init_session()

                if df is not None and not df.empty:
                    # 💡 性能修复：将多级 DataFrame 切片与 JSON 大序列化同步操作推入线程池，彻底保护事件循环  # noqa: E501
                    def _process_macro_data(local_df: pd.DataFrame):
                        daily_snap = {}
                        cache_list = []
                        alert_list = []
                        if local_df is None or not hasattr(local_df, "empty") or local_df.empty:  # noqa: E501
                            return daily_snap, cache_list, alert_list

                        for ticker in tickers:
                            try:
                                if isinstance(local_df.columns, pd.MultiIndex):
                                    if ticker in local_df.columns.levels[0] or ticker in local_df:  # noqa: E501
                                        ticker_df = local_df[ticker].dropna(how="all")
                                    elif "Close" in local_df:
                                        ticker_df = (
                                            local_df.xs(ticker, axis=1, level=1).dropna(how="all")
                                            if ticker in local_df.columns.get_level_values(1)
                                            else pd.DataFrame()
                                        )  # noqa: E501
                                    else:
                                        continue
                                else:
                                    ticker_df = local_df.dropna(how="all") if len(tickers) == 1 else pd.DataFrame()  # noqa: E501

                                if not ticker_df.empty:
                                    df_reset = ticker_df.reset_index()
                                    df_reset.columns = [str(c) for c in df_reset.columns]  # noqa: E501
                                    cache_list.append(
                                        (
                                            f"yf_macro_cache_{ticker}",
                                            df_reset.to_json(orient="records", date_format="iso"),
                                        )
                                    )  # noqa: E501

                                    try:
                                        if "Close" in ticker_df.columns:
                                            last_price = float(ticker_df["Close"].iloc[-1])  # noqa: E501
                                            last_dt = ticker_df.index[-1]
                                            last_date = last_dt.date() if hasattr(last_dt, "date") else None  # noqa: E501

                                            if len(ticker_df) > 1:
                                                prev_price_for_chg = float(ticker_df["Close"].iloc[-2])  # noqa: E501
                                            elif "Open" in ticker_df.columns:
                                                prev_price_for_chg = float(ticker_df["Open"].iloc[-1])  # noqa: E501
                                            else:
                                                prev_price_for_chg = last_price
                                            chg_pct = (
                                                (last_price - prev_price_for_chg) / prev_price_for_chg * 100
                                                if prev_price_for_chg > 0
                                                else 0.0
                                            )  # noqa: E501
                                            daily_snap[ticker] = {
                                                "price": last_price,
                                                "change": chg_pct,
                                                "date": last_date,
                                            }  # noqa: E501

                                            if ticker in last_minute_prices:
                                                prev_price = last_minute_prices[ticker]
                                                if prev_price > 0:
                                                    delta_pct = (last_price - prev_price) / prev_price * 100  # noqa: E501
                                                    threshold = 3.0 if "BTC" in ticker else 1.5  # noqa: E501
                                                    if abs(delta_pct) >= threshold:
                                                        direction = "暴力拉升 🚀" if delta_pct > 0 else "高台跳水 🩸"  # noqa: E501
                                                        alert_list.append(
                                                            f"🚨 [宏观异动预警] {ticker} 发生分钟级 {direction}!\n\n当前价: {last_price:,.2f}\n极速变动: {delta_pct:+.2f}%\n\n请密切关注全球系统性流动性风险！"
                                                        )  # noqa: E501
                                            last_minute_prices[ticker] = last_price
                                    except Exception as e:
                                        print(f"  ⚠️ [YF Daemon] 价格异动监控处理异常: {e}")  # noqa: E501
                            except Exception as e:
                                print(f"  ⚠️ [YF Daemon] 处理 {ticker} 批量数据异常: {e}")  # noqa: E501
                        return daily_snap, cache_list, alert_list

                    loop = asyncio.get_running_loop()
                    daily_snapshot, cache_updates, alerts = await loop.run_in_executor(
                        self._executor, _process_macro_data, df
                    )  # noqa: E501

                    from backend.core.redis_client import redis_batch_writer

                    for k, v in cache_updates:
                        ttl = 43200 + random.randint(100, 600)
                        # 💡 性能优化：改用异步高频批量写入队列，实现 Fire-and-Forget 零阻塞  # noqa: E501
                        redis_batch_writer.put_set_nowait(k, v, ex=ttl)
                        print(f"  ✅ [YF Daemon] 缓存已提交至异步队列 (Key: {k})")

                    for msg in alerts:
                        print(msg)
                        asyncio.create_task(notification_service.send_alert(msg))

                    # 💡 美东收盘大类资产总结推送 (美东时间 16:00)
                    try:
                        from datetime import datetime, timedelta, timezone

                        try:
                            import zoneinfo

                            tz = zoneinfo.ZoneInfo("America/New_York")
                        except Exception:
                            # 降级：如果系统缺失 tzdata，手动根据大致月份推算 (粗略版)
                            utc_now = datetime.now(timezone.utc)
                            is_dst = 3 <= utc_now.month <= 11
                            tz = timezone(timedelta(hours=-4 if is_dst else -5))

                        est_now = datetime.now(tz)
                        current_date = est_now.date()

                        # 💡 验证今天是否为真实交易日：提取美股大盘(^GSPC)最新K线的日期进行比对  # noqa: E501
                        is_trading_day = True
                        gspc_snap = daily_snapshot.get("^GSPC")
                        if gspc_snap and gspc_snap.get("date") and gspc_snap.get("date") != current_date:  # noqa: E501
                            is_trading_day = False

                        # 在美东时间下午 16 点 (16:00 ~ 16:59) 触发，且为交易日，每天只发一次  # noqa: E501
                        if (
                            est_now.hour == 16
                            and last_summary_date != current_date
                            and est_now.weekday() < 5
                            and is_trading_day
                        ):  # noqa: E501
                            last_summary_date = current_date
                            core_assets = {
                                "^GSPC": "标普500",
                                "^IXIC": "纳斯达克",
                                "^VIX": "恐慌指数",
                                "DX-Y.NYB": "美元指数",
                                "^TNX": "10年期美债",
                                "GC=F": "黄金",
                                "BTC-USD": "比特币",  # noqa: E501
                                "XLK": "科技板块",
                                "XLF": "金融板块",
                                "XLE": "能源板块",
                                "KWEB": "中概互联",  # noqa: E501
                            }
                            summary_lines = ["📊 [宏观收盘盘点] 全球核心大类资产今日收盘表现：\n"]  # noqa: E501
                            for t, name in core_assets.items():
                                if t in daily_snapshot:
                                    p = daily_snapshot[t]["price"]
                                    c = daily_snapshot[t]["change"]
                                    icon = "🟢" if c > 0 else "🔴" if c < 0 else "⚪"
                                    summary_lines.append(f"{icon} {name}: {p:,.2f} ({'+' if c > 0 else ''}{c:.2f}%)")  # noqa: E501

                            # 💡 新增：大模型盘后一句话犀利点评
                            try:
                                market_data_str = ", ".join(
                                    [
                                        f"{name} {daily_snapshot[t]['price']:.2f} ({'+' if daily_snapshot[t]['change'] > 0 else ''}{daily_snapshot[t]['change']:.2f}%)"
                                        for t, name in core_assets.items()
                                        if t in daily_snapshot
                                    ]
                                )  # noqa: E501

                                # 💡 提取今天最新的 5 条宏观头条新闻喂给大模型
                                recent_news = []
                                try:
                                    members = await redis_client.zrevrange("macro_news_stream", 0, 4)  # noqa: E501
                                    for m in members:
                                        if isinstance(m, (str, bytes, bytearray)):
                                            n_obj = json.loads(m)
                                            if n_obj.get("headline"):
                                                recent_news.append(n_obj["headline"])
                                except Exception as e:
                                    print(f"  ⚠️ [YF Daemon] 获取宏观新闻缓存失败: {e}")

                                news_str = f" 今日核心新闻: {'; '.join(recent_news)}。" if recent_news else ""  # noqa: E501
                                prompt = f"你是顶尖华尔街量化交易主脑。以下是今日全球核心资产收盘表现：{market_data_str}。{news_str}请结合 VIX 恐慌指数的绝对水位（低于15乐观，高于25恐慌）、大类资产的背离情况及新闻事件，用一两句话（毒舌、专业，不超过80字）点评今日资金博弈及宏观风险。"  # noqa: E501
                                resp = await self.llm_service.get_client().chat.completions.create(  # noqa: E501
                                    model=self.llm_service.get_model(),
                                    temperature=0.8,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                content = resp.choices[0].message.content
                                ai_comment = content.strip() if content else "暂无点评"

                                # 💡 剔除可能包含的大模型包裹标记 (如 ```markdown ... ```)  # noqa: E501
                                ai_comment = re.sub(r"^```[a-zA-Z]*\s*", "", ai_comment)
                                ai_comment = re.sub(r"\s*```$", "", ai_comment)
                                ai_comment = ai_comment.strip()

                                if ai_comment:
                                    summary_lines.append(f"\n🧠 [主脑点评] {ai_comment}")  # noqa: E501, E701
                            except Exception as e:
                                print(f"  ⚠️ [YF Daemon] AI 点评生成失败: {e}")

                            alert_msg = "\n".join(summary_lines)
                            print(alert_msg)
                            asyncio.create_task(notification_service.send_alert(alert_msg))
                    except Exception as e:
                        print(f"  ⚠️ [YF Daemon] 收盘总结推送异常: {e}")

                    print("✅ [YF Daemon] 本轮批量同步完毕，守护进程休眠 120 秒...")
                    base_interval = 120  # 恢复正常频率

                    # 💡 及时释放大对象：Pandas DataFrame 极占内存，必须在此销毁，防止在长达 120 秒的休眠期内发生幽灵驻留  # noqa: E501
                    df = None
                    daily_snapshot = None
                else:
                    print("  ⚠️ [YF Daemon] 批量获取为空数据，疑似触发软限流")
                    base_interval = min(3600, base_interval * 2)
                    print(f"🚨 [YF Daemon] 触发限流，下一轮休眠间隔拉长至 {base_interval} 秒")  # noqa: E501

            except Exception as e:
                print(f"❌ [YF Daemon] 批量拉取异常: {e}")
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    base_interval = min(3600, base_interval * 2)
                    print(f"🚨 [YF Daemon] 触发限流，下一轮整体休眠间隔拉长至 {base_interval} 秒")  # noqa: E501

            await asyncio.sleep(base_interval)


yf_service = YFinanceService()
