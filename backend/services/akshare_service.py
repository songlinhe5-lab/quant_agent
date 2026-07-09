"""
AKShare 数据源服务 — 港股通资金流向 (南向/北向)

负责从东方财富/沪深港通获取跨市场资金净买卖数据。
数据来源: akshare stock_hsgt_* 系列接口
缓存策略: Redis 60s TTL，避免频繁请求触发限流

运行模式 (环境变量 AKSHARE_MODE):
  - direct: 直连 akshare 库获取数据 (默认，主服务本地模式)
  - cache:  仅读取 Redis 缓存，不直连 akshare (加州主服务 + 北京 VPS 中继模式)
            数据由北京 VPS 的 AKShareCollector 定时采集写入 Redis
"""

import asyncio
import json
import os
import random
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from redis.exceptions import LockError

from backend.core.logger import logger
from backend.core.redis_client import redis_client
from backend.core.retry_utils import with_global_retry

# AKShare 运行模式: direct (直连 akshare) | cache (仅读 Redis 缓存)
_AKSHARE_MODE = os.getenv("AKSHARE_MODE", "direct").lower()


class AKShareService:
    """
    封装 AKShare 港股通资金流向数据获取逻辑。
    支持同步调用，由上层 macro.py 决定是否异步封装。
    """

    def __init__(self):
        self._circuit_breaker_until = 0.0  # 熔断器冷却结束的时间戳
        self._error_count = 0  # 连续错误计数器
        self._max_errors = 3  # 触发熔断的阈值
        self._cache_mode = _AKSHARE_MODE == "cache"
        if self._cache_mode:
            logger.info("[AKShare] 运行模式: cache (仅读取 Redis 缓存，数据由北京 VPS 中继)")

    def get_health_status(self) -> Dict[str, Any]:
        """获取东方财富 (AKShare) 接口的熔断与健康状态"""
        import time

        now = time.time()
        is_open = now < self._circuit_breaker_until
        mode_label = "cache (北京VPS中继)" if self._cache_mode else "direct (直连akshare)"
        return {
            "name": "AKShare (东方财富)",
            "mode": mode_label,
            "status": "circuit_open" if is_open else ("warning" if self._error_count > 0 else "healthy"),  # noqa: E501
            "cooldown_remaining": max(0, int(self._circuit_breaker_until - now)) if is_open else 0,  # noqa: E501
            "message": "触发反爬限流熔断中"
            if is_open
            else (f"已连续报错 {self._error_count} 次，接近熔断阈值" if self._error_count > 0 else "正常"),  # noqa: E501
        }

    @asynccontextmanager
    async def _acquire_lock_with_timeout(self, acquire_timeout: float = 5.0, exec_timeout: float = 15.0):  # noqa: E501
        # 💡 使用 Redis 实现分布式锁，防止多实例并发请求
        lock = redis_client.lock(
            "akshare_global_lock",
            timeout=exec_timeout,
            blocking_timeout=acquire_timeout,
        )  # noqa: E501
        try:
            async with lock:
                yield
        except LockError:
            raise TimeoutError(f"AKShare 接口调用排队超时 ({acquire_timeout}s)，分布式锁获取失败。")  # noqa: E501
        except asyncio.TimeoutError:  # This might be raised by the business logic inside the lock  # noqa: E501
            raise TimeoutError(f"AKShare 接口执行超时 ({exec_timeout}s)，底层数据源无响应。")  # noqa: E501

    # 沪深港通资金流向 — 东财实时接口名称映射
    # 注意: AKShare 的函数名带有 em (东方财富) 后缀
    # 实际调用时通过 akshare 的 stock_hsgt_* 函数

    @with_global_retry
    async def get_southbound_flow(self) -> Dict[str, Any]:
        """
        获取港股通南向资金当日累计净买入金额（亿元人民币）。
        数据来源: 东方财富沪深港通实时数据

        返回格式:
        {
            "status": "success",
            "data": {
                "net_inflow": 12.8,       # 当日南向净买入 (亿人民币)
                "balance": 105.0,         # 当日余额
                "quota": 105.0,           # 每日额度
                "date": "2026-06-03",
                "sparkline": [...],       # 近8日净流入序列
            }
        }
        """
        cache_key = "akshare_southbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        # DIST-07 方案A: cache 模式下不直连 akshare，数据由北京 VPS 中继写入 Redis
        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 南向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            import akshare as ak

            # stock_hsgt_fund_flow_summary_em: 沪深港通资金流向汇总
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁：防止排队的并发请求将缓存击穿
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                # 💡 并发拉取 实时汇总 和 历史趋势
                df, hist_df = await asyncio.gather(
                    asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em),
                    asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="南向资金"),
                    return_exceptions=True,
                )

            if isinstance(df, BaseException) or df is None or df.empty:
                raise ValueError(f"获取到的资金流向汇总数据异常: {df}")

            # 筛选南向资金 (包含港股通沪与港股通深)
            south_df = df[df["资金方向"] == "南向"]
            if south_df.empty:
                raise ValueError("未在数据中找到南向资金方向的明细")

            net_inflow = float(south_df["资金净流入"].sum())

            date_str = str(south_df["交易日"].iloc[0])

            # 💡 提取真实的近期历史趋势线
            sparkline = [1, 1, -1, 1, 1, 1, -1, 1]
            if not isinstance(hist_df, BaseException) and hist_df is not None and not hist_df.empty:  # noqa: E501
                # 💡 修复：优先使用 "当日成交净买额" (真实净买卖) 而非 "当日资金流入" (额度占用)  # noqa: E501
                target_col = "当日成交净买额" if "当日成交净买额" in hist_df.columns else "当日资金流入"  # noqa: E501
                if target_col in hist_df.columns:
                    sparkline = hist_df[target_col].tail(8).astype(float).tolist()
                    # 💡 智能拯救：如果实时接口返回了额度占位符(>800亿)，利用历史趋势的最后一天真实数据进行替换拯救！  # noqa: E501
                    if net_inflow >= 800.0 and len(sparkline) > 0:
                        net_inflow = float(sparkline[-1])

            if net_inflow >= 800.0:
                raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")  # noqa: E501

            # 状态判定：3 为已收盘
            is_closed = int(south_df["交易状态"].iloc[0]) == 3 if "交易状态" in south_df.columns else False  # noqa: E501

            result = {
                "status": "success",
                "data": {
                    "net_inflow": round(net_inflow, 2),
                    "unit": "亿人民币",
                    "date": date_str,
                    "sparkline": sparkline,
                },
                "is_closed": is_closed,
                "source": "akshare_stock_hsgt_fund_flow_summary",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] 南向资金获取失败: {e}")
            result = self._mock_southbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 成功时智能缓存：盘中缓存 5 分钟，已收盘则长效缓存 12 小时
        if result.get("status") == "success":
            # 💡 增加随机 Jitter 防雪崩
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_northbound_flow(self) -> Dict[str, Any]:
        """
        获取北向资金（外资买入A股）当日累计净买入金额。

        返回格式:
        {
            "status": "success",
            "data": {
                "net_inflow": -5.3,
                "unit": "亿人民币",
                "date": "2026-06-03",
                "sparkline": [...],
            }
        }
        """
        cache_key = "akshare_northbound_flow"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": "cache 模式: 北向资金缓存未命中，等待北京 VPS 采集器写入",
                "data": None,
            }

        try:
            import akshare as ak

            # stock_hsgt_fund_flow_summary_em: 沪深港通资金流向汇总
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁：防止排队的并发请求将缓存击穿
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                # 💡 并发拉取 实时汇总 和 历史趋势
                df, hist_df = await asyncio.gather(
                    asyncio.to_thread(ak.stock_hsgt_fund_flow_summary_em),
                    asyncio.to_thread(ak.stock_hsgt_hist_em, symbol="北向资金"),
                    return_exceptions=True,
                )

            if isinstance(df, BaseException) or df is None or df.empty:
                raise ValueError(f"获取到的资金流向汇总数据异常: {df}")

            # 筛选北向资金 (包含沪股通与深股通)
            north_df = df[df["资金方向"] == "北向"]
            if north_df.empty:
                raise ValueError("未在数据中找到北向资金方向的明细")

            net_inflow = float(north_df["资金净流入"].sum())

            date_str = str(north_df["交易日"].iloc[0])

            # 💡 提取真实的近期历史趋势线
            sparkline = [-1, -1, 1, -1, -1, 1, -1, -1]
            if not isinstance(hist_df, BaseException) and hist_df is not None and not hist_df.empty:  # noqa: E501
                # 💡 修复：优先使用 "当日成交净买额" (真实净买卖) 而非 "当日资金流入" (额度占用)  # noqa: E501
                target_col = "当日成交净买额" if "当日成交净买额" in hist_df.columns else "当日资金流入"  # noqa: E501
                if target_col in hist_df.columns:
                    sparkline = hist_df[target_col].tail(8).astype(float).tolist()
                    # 💡 智能拯救北向：如果实时接口返回额度占位符(>1000亿)
                    if net_inflow >= 1000.0 and len(sparkline) > 0:
                        net_inflow = float(sparkline[-1])

            # 状态判定：3 为已收盘
            is_closed = int(north_df["交易状态"].iloc[0]) == 3 if "交易状态" in north_df.columns else False  # noqa: E501

            # 💡 健壮性修复：如果返回的值大于等于每日总额度(1000亿以上)，说明接口异常
            if net_inflow >= 1000.0:
                raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")  # noqa: E501

            result = {
                "status": "success",
                "data": {
                    "net_inflow": round(net_inflow, 2),
                    "unit": "亿人民币",
                    "date": date_str,
                    "sparkline": sparkline,
                },
                "is_closed": is_closed,
                "source": "akshare_stock_hsgt_fund_flow_summary",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] 北向资金获取失败: {e}")
            result = self._mock_northbound()

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 成功时智能缓存：盘中缓存 5 分钟，已收盘则长效缓存 12 小时
        if result.get("status") == "success":
            # 💡 增加随机 Jitter 防雪崩
            ttl = (43200 if result.get("is_closed") else 300) + random.randint(10, 60)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)
        return result

    @with_global_retry
    async def get_hsgt_top_holders(self, symbol: str = "00700") -> Dict[str, Any]:
        """
        获取沪深港通个股持仓明细（按参与机构汇总），用于推算外资/南下托管行持股变化。
        (已升级为使用 stock_hsgt_individual_detail_em 获取更精准的互联互通机构明细)

        参数:
            symbol: 纯数字代码，如 "00700" (港股) 或 "002008" (A股)

        返回:
            {
                "status": "success",
                "data": {
                    "symbol": "00700",
                    "total_shares": ...,
                    "participants": [...],
                    "southbound_proxy": ...  # 南下资金托管行合计
                }
            }
        """
        cache_key = f"akshare_hsgt_holders_{symbol}"
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)

        if self._cache_mode:
            return {
                "status": "no_data",
                "message": f"cache 模式: {symbol} 持股明细缓存未命中",
                "data": None,
            }

        try:
            import akshare as ak

            # 动态推断最近 20 天以确保命中交易日
            today = datetime.now()
            end_date = today.strftime("%Y%m%d")
            start_date = (today - timedelta(days=20)).strftime("%Y%m%d")

            # stock_hsgt_individual_detail_em: 沪深港通具体股票机构持股详情 (替代废弃的 CCASS 接口)  # noqa: E501
            async with self._acquire_lock_with_timeout(5.0):
                # 💡 双重检查锁
                cached_double = await redis_client.get(cache_key)
                if cached_double:
                    return json.loads(cached_double)

                df = await asyncio.to_thread(
                    ak.stock_hsgt_individual_detail_em,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                )
            if df is None or df.empty:
                raise ValueError(f"沪深港通持股明细数据为空 ({symbol})")

            # 获取最近两个交易日的日期
            dates = sorted(df["持股日期"].unique(), reverse=True)
            latest_date = dates[0]
            prev_date = dates[1] if len(dates) > 1 else None

            # 筛选最新与上一交易日的数据
            latest_df = df[df["持股日期"] == latest_date]
            prev_df = df[df["持股日期"] == prev_date] if prev_date else None

            # 构建上一交易日机构持仓映射表，用于对比计算
            prev_map = (
                {str(row.get("机构名称", "")): float(row.get("持股数量", 0) or 0) for _, row in prev_df.iterrows()}
                if prev_df is not None and not prev_df.empty
                else {}
            )  # noqa: E501

            # 按照持股数量降序排列以获取 Top 机构
            if "持股数量" in latest_df.columns:
                latest_df = latest_df.sort_values(by="持股数量", ascending=False)

            # 极其精准的南向/北向总股数 (直接进行全表加和)
            southbound_total = float(latest_df["持股数量"].sum())
            prev_southbound_total = (
                float(prev_df["持股数量"].sum()) if prev_df is not None and not prev_df.empty else southbound_total
            )  # noqa: E501
            total_net_change = southbound_total - prev_southbound_total
            total_holdings = southbound_total

            participants_summary = []
            for _, row in latest_df.head(20).iterrows():
                holder = str(row.get("机构名称", ""))
                shares = float(row.get("持股数量", 0) or 0)
                pct = float(row.get("持股数量占A股百分比", row.get("占已发行股份百分比", 0)) or 0)  # noqa: E501

                # 计算该机构的净增持
                prev_shares = prev_map.get(holder, shares)
                net_change = shares - prev_shares

                participants_summary.append(
                    {
                        "holder": holder,
                        "shares": round(shares, 0),
                        "net_change": round(net_change, 0),
                        "pct": round(pct, 2),
                        "is_southbound": True,  # 来源于沪深港通接口，全部为互联互通资金
                    }
                )

            result = {
                "status": "success",
                "data": {
                    "symbol": symbol,
                    "date": str(latest_date),
                    "southbound_total_shares": round(southbound_total, 0),
                    "southbound_net_change": round(total_net_change, 0),
                    "participants": participants_summary,
                    "total_shares_sampled": round(total_holdings, 0),
                },
                "source": "akshare_stock_hsgt_individual_detail",
            }
        except Exception as e:
            print(f"⚠️ [AKShare] CCASS {symbol} 获取失败: {e}")
            result = {
                "status": "warning" if isinstance(e, ValueError) else "error",
                "message": str(e),
                "data": None,
            }

        result["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 仅当获取成功时进行 12 小时长效缓存 (互联互通明细为 T-1 盘后数据，每天更新一次即可)  # noqa: E501
        if result.get("status") == "success":
            ttl = 43200 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
        else:
            await redis_client.set(cache_key, json.dumps(result), ex=60)  # 错误状态仅做短时防穿透  # noqa: E501
        return result

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
                self._circuit_breaker_until = time.time() + 60.0

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
                self._circuit_breaker_until = time.time() + 60.0

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
                self._circuit_breaker_until = time.time() + 60.0

            return {"status": "error", "message": f"K线异常: {e}"}

    # ── Mock 兜底 ───────────────────────────────────────────────────────

    def _mock_southbound(self) -> dict:
        return {
            "status": "warning",
            "message": "南向资金数据获取失败，使用模拟数据",
            "data": {
                "net_inflow": 12.8,
                "unit": "亿人民币",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "sparkline": [1, 1, -1, 1, 1, 1, -1, 1],
            },
            "source": "mock",
        }

    def _mock_northbound(self) -> dict:
        return {
            "status": "warning",
            "message": "北向资金数据获取失败，使用模拟数据",
            "data": {
                "net_inflow": -5.3,
                "unit": "亿人民币",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "sparkline": [-1, -1, 1, -1, -1, 1, -1, -1],
            },
            "source": "mock",
        }

    @with_global_retry
    async def get_economic_calendar(self, days_ahead: int = 7, skip_cache: bool = False) -> Dict[str, Any]:  # noqa: E501
        """
        通过 百度股市通 / 新浪财经 / 金十数据 (Jin10) 三重接口聚合获取宏观经济日历。
        构建三级容灾架构，彻底解决单一接口被封控导致的无数据问题。
        """
        cache_key = f"akshare_jin10_calendar_{days_ahead}"
        if not skip_cache:
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)

            if self._cache_mode:
                return {
                    "status": "no_data",
                    "message": "cache 模式: 宏观日历缓存未命中，等待北京 VPS 采集器写入",
                    "data": [],
                }

        # 国内数据源使用北京时间 (东八区)
        tz_cn = timezone(timedelta(hours=8))
        today = datetime.now(tz_cn)

        dates_to_fetch = []
        for i in range(days_ahead + 1):
            dt = today + timedelta(days=i)
            dates_to_fetch.append((dt.strftime("%Y-%m-%d"), dt.strftime("%Y%m%d")))

        async def _fetch_date(date_str: str, date_compact: str):
            # 1. 尝试 AKShare 百度股市通 (正规，带中文)
            try:
                import akshare as ak

                if hasattr(ak, "news_economic_baidu"):
                    df = await asyncio.to_thread(ak.news_economic_baidu, date=date_compact)  # noqa: E501
                    if df is not None and not df.empty:
                        return df.to_dict("records")
            except Exception:
                pass

            # 2. 尝试裸请求 Sina 新浪财经 (老牌接口，极度稳定无反爬)
            try:
                import httpx

                url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.get_eco_calendar?date={date_str}"
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list) and data:
                            return data
            except Exception:
                pass

            # 3. 尝试裸请求 Jin10 (加满伪装)
            try:
                import httpx

                url = f"https://rili-api.jin10.com/get_list?date={date_str}"
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://rili.jin10.com/",
                }
                async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json().get("data", [])
                        if isinstance(data, list) and data:
                            return data
            except Exception:
                pass

            return []

        events = []
        try:
            results = await asyncio.gather(
                *[_fetch_date(d_str, d_compact) for d_str, d_compact in dates_to_fetch],
                return_exceptions=True,
            )  # noqa: E501
            for date_idx, res in enumerate(results):
                if isinstance(res, BaseException) or not isinstance(res, list):
                    continue

                target_date_str = dates_to_fetch[date_idx][0]

                for item in res:
                    if not isinstance(item, dict):
                        continue  # noqa: E701

                    # 万能提取器：兼容百度、新浪、金十三种不同的字段规范
                    country = str(item.get("地区", item.get("country", item.get("国家", ""))))  # noqa: E501
                    event_name = str(
                        item.get(
                            "事件",
                            item.get("event", item.get("指标名称", item.get("name", ""))),
                        )
                    ).strip()  # noqa: E501
                    if not event_name:
                        continue  # noqa: E701

                    # 星级/重要性
                    star = str(item.get("重要性", item.get("importance", item.get("star", ""))))  # noqa: E501
                    impact = (
                        "high" if "高" in star or "3" in star else ("medium" if "中" in star or "2" in star else "low")
                    )  # noqa: E501

                    # 时间处理 (如果未提供具体时间，默认 08:30)
                    pub_time = str(
                        item.get(
                            "公布时间",
                            item.get("时间", item.get("time", item.get("pub_time", ""))),
                        )
                    )  # noqa: E501
                    if not pub_time or pub_time.lower() == "nan" or ":" not in pub_time:
                        full_time = f"{target_date_str} 08:30:00"
                    else:
                        full_time = f"{target_date_str} {pub_time}" if len(pub_time) <= 8 else pub_time  # noqa: E501

                    events.append(
                        {
                            "time": full_time,
                            "country": country,
                            "event": event_name,
                            "impact": impact,
                            "previous": str(
                                item.get(
                                    "前值",
                                    item.get("previous_value", item.get("previous", "")),
                                )
                            ),  # noqa: E501
                            "estimate": str(
                                item.get(
                                    "预测值",
                                    item.get("predicted_value", item.get("consensus", "")),
                                )
                            ),  # noqa: E501
                            "actual": str(
                                item.get(
                                    "公布值",
                                    item.get("actual_value", item.get("actual", "")),
                                )
                            ),  # noqa: E501
                        }
                    )

            # 按时间正序排列
            events.sort(key=lambda x: x["time"])

            result = {
                "status": "success",
                "data": events,
                "source": "akshare_universal",
            }  # noqa: E501
            # 缓存半天 + 随机抖动防雪崩
            ttl = 43200 + random.randint(100, 600)
            await redis_client.set(cache_key, json.dumps(result), ex=ttl)
            return result
        except Exception as e:
            return {"status": "error", "message": f"Jin10 宏观日历请求异常: {str(e)}"}


# 全局单例
akshare_service = AKShareService()
