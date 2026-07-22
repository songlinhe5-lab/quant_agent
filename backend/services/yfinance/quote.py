"""微批处理行情拉取 Mixin"""

import asyncio
import random
import time
from typing import Any, Dict, Optional, cast

import pandas as pd
import yfinance as yf

from backend.services.yfinance.utils import format_yf_ticker


class QuoteMixin:
    """微批处理 (Micro-batching) 行情加载器"""

    async def get_batched_quote(self, ticker: str, req_type: str = "quote", **kwargs) -> Dict[str, Any]:  # noqa: E501
        """
        💡 革命性优化：基于微批处理 (Micro-batching) 的异步数据加载器。
        支持动态混入 "quote" (实时行情) 和 "tech" (技术指标) 类型的合并请求。
        """
        # ── DIST-04: 路由器模式拦截 ──
        if self._router_enabled:
            await self._ensure_router()
            payload = {"ticker": ticker, "req_type": req_type, **kwargs}
            cache_key_r = f"batch:{ticker}:{req_type}"
            result = await self._router.call(
                "batch_quote",
                payload,
                cache_key=cache_key_r,
            )
            if result.get("status") == "success":
                return result
            return {"status": "error", "message": result.get("message", "路由器: 批量行情获取失败")}

        yf_ticker = format_yf_ticker(ticker)
        
        # 💡 1. 使用统一熔断器：cb.call() 自动处理 OPEN/HALF_OPEN 状态
        try:
            async def _do_quote_fetch():
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
        
                # 💡 3. 检查黑名单 (5 分钟冷却，防止退市/错误标的引发重复超时卡顿)
                if cache_key in self._error_cache and (now - self._error_cache[cache_key] < 300.0):  # noqa: E501
                    return {"status": "error", "message": f"{ticker} 数据拉取频繁失败，冷却中"}
        
                loop = asyncio.get_running_loop()
                # 交给业务方一个“取餐号” (Future)，业务方会原地 await 等待数据
                fut = loop.create_future()
                # TODO: 后续实现实际的数据获取逻辑
                        
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
