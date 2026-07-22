"""宏观数据后台守护进程 Mixin"""

import asyncio
import json
import random
import re
import time

import pandas as pd
import yfinance as yf

from backend.services.notification_service import notification_service


class MacroDaemonMixin:
    """宏观数据定时批量拉取守护进程"""

    async def macro_data_daemon(self) -> None:
        """后台守护进程：定时批量拉取宏观指标，彻底解决 YFinance 429 封控"""
        # ── DIST-04: 路由器模式下由远程数据源节点负责采集，本地不启动 daemon ──
        if self._router_enabled:
            from backend.core.logger import logger

            logger.info("[YF Daemon] 路由器模式已启用，宏观数据采集由远程节点负责，本地 daemon 休眠中")
            await asyncio.sleep(3600)
            return

        from backend.core.redis_client import redis_client

        # 需要高频守护的全球宏观指标与大盘代码 (严格对齐数据中心面板的 12 大资产)
        tickers = [
            "^GSPC",
            "^IXIC",
            "^HSI",
            "HSTECH.HK",  # 💡 恒生科技指数 Yahoo 代码
            "^TNX",
            "JPY=X",
            "DX-Y.NYB",
            "USDCNH=X",  # 💡 修复: USD/CNH 正确代码
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
                            print("  🚨 [YF Daemon] 触发限流错误，记录失败以触发熔断")
                            self.cb.record_failure("yf_api")  # 触发熔断器自动管理冷却
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
