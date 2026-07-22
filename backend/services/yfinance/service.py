"""YFinanceService 主类：核心初始化 + 数据拉取引擎"""

import asyncio
import os
import random
import time
from typing import Any, Dict, Tuple

import yfinance as yf

from backend.core.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from backend.core.graceful_executor import GracefulExecutor
from backend.services.yfinance.macro_daemon import MacroDaemonMixin
from backend.services.yfinance.quote import QuoteMixin
from backend.services.yfinance.search import SearchMixin
from backend.services.yfinance.technical import TechnicalMixin
from backend.services.yfinance.utils import RateLimitedSession, format_yf_ticker

# 💡 内存安全防御：缓存容量上限 + TTL 清理
_YF_CACHE_MAX_SIZE = 500  # 最多缓存 500 个条目
_YF_CACHE_TTL = 600  # 缓存 TTL 10 分钟
_YF_ERROR_CACHE_TTL = 300  # 错误黑名单 TTL 5 分钟


class YFinanceService(QuoteMixin, TechnicalMixin, SearchMixin, MacroDaemonMixin):
    def __init__(self, llm_service_instance=None):
        self._cache = {}  # { cache_key: (timestamp, data) }
        self._error_cache = {}  # { cache_key: timestamp } 黑名单缓存
        self._req_lock = asyncio.Lock()
        self._last_req_time = 0.0
        self.cb = get_circuit_breaker()

        # llm_service 支持依赖注入：测试时可传入 mock，生产环境使用全局单例
        self._llm_service_override = llm_service_instance

        # 💡 ARCH-03: 使用 GracefulExecutor 支持异步优雅关闭
        self._executor = GracefulExecutor(
            max_workers=10,
            thread_name_prefix="YFinanceWorker",
            max_wait_s=30
        )

        # 💡 微批处理队列机制 (Micro-batching Queue / DataLoader)
        self._batch_queue = {}
        self._batch_lock = asyncio.Lock()
        self._batch_dispatch_task = None

        self._init_session()

        # ── DIST-04: 路由器兼容外壳 ──
        # YF_ROUTER_ENABLED=true 时，通过 YFinanceRouter 将请求代理到远程数据源节点，
        # 上层调用方 (data_source_router / market router / collector) 零改动。
        self._router_enabled: bool = os.getenv("YF_ROUTER_ENABLED", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        self._router = None  # 懒初始化 (需要 async 上下文)
        self._router_init_lock = asyncio.Lock()

    async def _ensure_router(self):
        """懒初始化 YFinanceRouter (首次异步调用时触发)"""
        if self._router is not None:
            return
        async with self._router_init_lock:
            if self._router is not None:
                return
            from backend.core.redis_client import redis_client
            from backend.core.service_registry import ServiceRegistry
            from backend.core.yfinance_router import YFinanceRouter

            registry = ServiceRegistry(redis_client)
            hmac_secret = os.getenv("DATA_SOURCE_HMAC_SECRET", "")
            self._router = YFinanceRouter(
                service_registry=registry,
                redis_client=redis_client,
                hmac_secret=hmac_secret,
            )

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

    async def async_close(self):
        """
        ARCH-03: 异步优雅关闭 - 等待所有任务完成

        改进:
        ✅ ThreadPoolExecutor 改为 graceful_shutdown()（支持 timeout）
        ✅ Session.close() 保持不变（同步操作）
        ✅ Router 关闭保持异步逻辑
        """
        print("🛑 [YFinanceService] 开始优雅关闭...")

        try:
            # 1. 关闭 requests.Session
            if hasattr(self, "session") and self.session:
                self.session.close()
                print("✅ YFinanceSession 已关闭")
        except Exception as e:
            print(f"⚠️ YFinanceSession 关闭异常：{e}")

        try:
            # 2. Graceful Executor shutdown
            if hasattr(self, "_executor") and self._executor:
                executor = self._executor
                stats = executor.get_stats()
                print(f"📊 Executor Stats before shutdown: {stats}")

                await executor.graceful_shutdown(timeout_s=30)
                print(f"✅ Executor 优雅关闭完成 (active_tasks={stats['active_tasks']})")
        except Exception as e:
            print(f"⚠️ Executor 关闭异常：{e}")

        try:
            # 3. 关闭路由器 HTTP 客户端
            if self._router is not None:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    await self._router.close()
                else:
                    await asyncio.get_event_loop().run_until_complete(self._router.close())
                self._router = None
                print("✅ YFinanceRouter 已关闭")
        except Exception as e:
            print(f"⚠️ Router 关闭异常：{e}")

        print("✅ YFinanceService 完全关闭完成")

    def get_health_status(self) -> Dict[str, Any]:
        """获取当前雅虎财经接口的熔断与健康状态"""
        # DIST-03: 使用统一熔断器状态查询
        cb_state = self.cb.get_state("yf_api")
        status = {
            "name": "Yahoo Finance",
            "status": cb_state.value,
            "cooldown_remaining": 0,
            "message": "触发 429 限流熔断中" if cb_state.value == "open" else "正常",
        }
        # DIST-04: 标注路由器模式
        if self._router_enabled:
            status["router_mode"] = True
            status["message"] = "路由器模式 (请求代理到远程数据源节点)"
        return status

    async def fetch_yf_data(
        self, ticker: str, fetch_type: str, ttl: int, persist: bool = False, **kwargs
    ) -> Tuple[bool, Any, str]:  # noqa: E501
        if os.getenv("QUANT_ENV") == "development" and yf is None:
            return False, None, "development_mock"
        if yf is None:
            return False, None, "环境缺失 yfinance 依赖"

        # ── DIST-04: 路由器模式拦截 ──
        if self._router_enabled:
            await self._ensure_router()
            cache_key_r = f"yf_{fetch_type}_{ticker}" + (
                "_" + "_".join([f"{k}_{v}" for k, v in kwargs.items()]) if kwargs else ""
            )
            payload = {
                "ticker": ticker,
                "fetch_type": fetch_type,
                "ttl": ttl,
                "persist": persist,
                **kwargs,
            }
            result = await self._router.call(
                "yfinance",
                payload,
                cache_key=cache_key_r,
            )
            if result.get("status") == "success" and "data" in result:
                return True, result["data"], ""
            return False, None, result.get("message", "路由器：数据获取失败")

        yf_ticker = format_yf_ticker(ticker)
        cache_key = f"yf_{fetch_type}_{yf_ticker}" + (
            "_" + "_".join([f"{k}_{v}" for k, v in kwargs.items()]) if kwargs else ""
        )

        # 🚨 使用统一熔断器：cb.call() 会自动处理 OPEN/HALF_OPEN 状态
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

            data = await self.cb.call("yf_api", _rate_limited_fetch)

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
                f"⚠️ [YFinance API] 获取到空数据 (疑似软限流/Cookie 失效) -> Ticker: {yf_ticker}"
            )  # noqa: E501
            return False, None, "软限流：返回空数据"

        except CircuitBreakerOpenError:
            return False, None, "限流冷却中：yfinance 触发全局熔断，请等待 60 秒后重试"
        except Exception as e:
            self._error_cache[cache_key] = time.time()  # 记录进黑名单
            err_str = str(e)
            print(f"⚠️ [YFinance] 外层兜底异常 | ticker: {yf_ticker} | fetch_type: {fetch_type} | error: {err_str}")  # noqa: E501
            return False, None, f"yfinance 未知系统异常：{err_str}"
