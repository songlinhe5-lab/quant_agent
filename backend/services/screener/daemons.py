"""后台守护进程 Mixin：订阅执行 / 每日强势股盘点 / 知识库清理"""

import asyncio
import json
import re
from datetime import datetime

from backend.core import models
from backend.core.database import SessionLocal, engine
from backend.core.redis_client import redis_client
from backend.services.futu import futu_service
from backend.services.llm_service import llm_service
from backend.services.notification_service import notification_service


class DaemonMixin:
    """提供后台定时守护进程能力的 Mixin"""

    # AI-04: 分类 TTL 映射 (秒)
    CATEGORY_TTL = {
        "financial_report": 90 * 24 * 3600,
        "news": 7 * 24 * 3600,
        "macro": 30 * 24 * 3600,
        "general": 90 * 24 * 3600,
    }

    async def screener_subscription_daemon(self) -> None:
        """后台任务：每天 18:00 自动执行订阅的选股条件，并通过通知渠道推送"""

        # 💡 同步 DB 操作隔离：将 SQLAlchemy 查询/提交封装为独立函数，通过 to_thread 执行，防止阻塞事件循环
        def _fetch_due_subscriptions(time_str: str):
            """线程安全：查询到达触发时间的活跃订阅"""
            with SessionLocal() as db:
                subs = (
                    db.query(models.ScreenerSubscription)
                    .filter(
                        models.ScreenerSubscription.is_active,
                        models.ScreenerSubscription.trigger_time == time_str,
                    )
                    .all()
                )
                # 序列化为轻量字典列表，避免 ORM 对象跨线程泄漏
                return [
                    {
                        "id": s.id,
                        "name": s.name,
                        "dsl": s.dsl,
                        "last_triggered_at": s.last_triggered_at,
                    }
                    for s in subs
                ]

        def _mark_triggered(sub_id: str, trigger_time):
            """线程安全：更新订阅的 last_triggered_at 防重触发"""
            with SessionLocal() as db:
                sub = db.query(models.ScreenerSubscription).filter(models.ScreenerSubscription.id == sub_id).first()
                if sub:
                    sub.last_triggered_at = trigger_time
                    db.commit()

        while True:
            try:
                now = datetime.now()
                current_time_str = now.strftime("%H:%M")

                subs_to_run = await asyncio.to_thread(_fetch_due_subscriptions, current_time_str)

                if subs_to_run:
                    print(
                        f"🚀 [Screener Daemon] {current_time_str} - 检测到 {len(subs_to_run)} 个订阅任务到达触发时间..."
                    )  # noqa: E501

                for sub in subs_to_run:
                    # 核心防重触发机制：检查上次触发是否在今天
                    if sub["last_triggered_at"] and sub["last_triggered_at"].date() == now.date():  # noqa: E501
                        print(f"🟡 [Screener Daemon] 任务 '{sub['name']}' 今日已触发过，跳过。")  # noqa: E501
                        continue

                    # 💡 分布式锁防重复执行：防止多节点并发时，同一用户的同一任务被多台机器一起执行并重复推送  # noqa: E501
                    lock_key = f"quant:lock:screener_sub:{sub['id']}:{now.strftime('%Y%m%d')}"  # noqa: E501
                    if not await redis_client.set(lock_key, "1", nx=True, ex=86400):
                        continue

                    print(f"  -> 🚀 [Screener Daemon] 开始执行订阅任务: {sub['name']}")
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            markets, futu_filters, post_filters = self.parse_dsl_to_futu_filters(sub["dsl"])  # noqa: E501
                            tasks = [futu_service.screen_stocks(market=m, filters=futu_filters) for m in markets]  # type: ignore  # noqa: E501
                            results = await asyncio.gather(*tasks, return_exceptions=True)  # noqa: E501

                            final_data = []
                            has_error = False
                            error_msg = ""
                            for res in results:
                                if isinstance(res, BaseException):
                                    has_error = True
                                    error_msg = str(res)
                                elif isinstance(res, dict) and res.get("status") == "success":  # noqa: E501
                                    final_data.extend(res.get("data", []))
                                elif isinstance(res, dict) and res.get("status") == "error":  # noqa: E501
                                    has_error = True
                                    error_msg = res.get("message", "Unknown error")

                            if has_error and not final_data:
                                raise ValueError(f"底层筛选 API 失败: {error_msg}")

                            # 内存二次过滤
                            if post_filters.get("exclude_st"):
                                final_data = [
                                    r
                                    for r in final_data
                                    if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")
                                ]  # noqa: E501

                            # 内存技术面二次过滤
                            tech_patterns = post_filters.get("technical_patterns", [])  # noqa: E501
                            if final_data:
                                final_data = await self.apply_technical_pattern_filtering(final_data, tech_patterns)  # noqa: E501

                            if final_data:
                                top_10 = final_data[:10]

                                # 💡 并发拉取这 10 只股票的最新一条新闻
                                async def _fetch_latest_news(ticker):
                                    try:
                                        is_asian = (
                                            any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()
                                        )  # noqa: E501
                                        if is_asian:
                                            from backend.services.data_source_router import (  # noqa: E501
                                                data_source_router,
                                            )

                                            res = await data_source_router.fetch_akshare("news", ticker=ticker)  # noqa: E501
                                        else:
                                            from backend.services.finnhub_service import (  # noqa: E501
                                                finnhub_service,
                                            )

                                            res = await finnhub_service.get_company_news(ticker, days_back=3)  # noqa: E501
                                        if res.get("status") == "success" and res.get("data"):  # noqa: E501
                                            return res["data"][0].get("headline", "")  # noqa: E501
                                    except Exception:
                                        pass
                                    return ""

                                news_list = await asyncio.gather(
                                    *[_fetch_latest_news(r["symbol"]) for r in top_10],
                                    return_exceptions=True,
                                )  # noqa: E501

                                # 💡 组装信息让大模型进行一句话点评
                                stock_contexts = []
                                for r, news in zip(top_10, news_list):
                                    if isinstance(news, BaseException):
                                        news = ""  # noqa: E701
                                    chg = r.get(
                                        "chg",
                                        r.get(
                                            "price_change_pct",
                                            r.get("change_rate", 0),
                                        ),
                                    )  # noqa: E501
                                    news_str = f", 最新动态: {news}" if news else ""
                                    stock_contexts.append(
                                        f"- {r.get('name', r['symbol'])} ({r['symbol']}): 今日涨跌 {chg:.2f}%{news_str}"
                                    )  # noqa: E501

                                stocks_info_str = "\n".join(stock_contexts)
                                llm_comments = ""

                                try:
                                    prompt = f"你是华尔街顶级量化分析师。以下是系统刚筛选出的 {len(top_10)} 只金股及最新盘面动态：\n\n{stocks_info_str}\n\n请你用毒舌、专业的金融黑话，为每只股票写一句精简的短评（结合其涨跌幅和最新新闻，判断其动能或风险）。\n格式要求严格如下：\n- **[股票名称]**: [一句话短评]"  # noqa: E501
                                    resp = await llm_service.get_client().chat.completions.create(  # noqa: E501
                                        model=llm_service.get_model(),
                                        temperature=0.7,
                                        messages=[{"role": "user", "content": prompt}],  # noqa: E501
                                    )
                                    content = resp.choices[0].message.content
                                    llm_comments = content.strip() if content else ""  # noqa: E501
                                    llm_comments = re.sub(r"^```[a-zA-Z]*\n", "", llm_comments)  # noqa: E501
                                    llm_comments = re.sub(r"\n```$", "", llm_comments).strip()  # noqa: E501
                                except Exception as e:
                                    print(f"⚠️ [Screener Daemon] LLM 点评失败: {e}")
                                    llm_comments = "\n".join(
                                        [f"- **{r.get('name', r['symbol'])}**: 暂无点评 (LLM 解析失败)" for r in top_10]
                                    )  # noqa: E501

                                tech_str = f"\n\n⚙️ 命中技术形态: {', '.join(tech_patterns)}" if tech_patterns else ""  # noqa: E501
                                msg = f"🔔 [智能选股日报] {sub['name']}\n\nAgent 根据您的订阅条件，在全市场扫盘发现 {len(final_data)} 只符合条件的标的。{tech_str}\n\n🔥 核心金股 Top 10 点评:\n{llm_comments}"  # noqa: E501
                                await notification_service.send_alert(msg)
                            else:
                                # 没有任何结果，也推送报告
                                msg = f"🔔 [智能选股日报] {sub['name']}\n\nAgent 扫盘完成，今日全市场未匹配到符合您严苛条件的标的。"  # noqa: E501
                                await notification_service.send_alert(msg)

                            # 💡 成功发送或无结果后，更新数据库中的 last_triggered_at 时间戳，防死循环  # noqa: E501
                            await asyncio.to_thread(_mark_triggered, sub["id"], now)
                            print(f"  -> ✅ [Screener Daemon] 任务 '{sub['name']}' 执行并推送完毕，已更新触发时间。")  # noqa: E501
                            break  # 退出重试循环

                        except Exception as inner_e:
                            print(f"⚠️ [Screener Daemon] 执行子任务 {sub['name']} 失败 (第 {attempt + 1} 次): {inner_e}")  # noqa: E501
                            if attempt < max_retries - 1:
                                await asyncio.sleep(10 * (attempt + 1))  # 失败后线性退避休眠再试  # noqa: E501
                            else:
                                # 彻底失败，推送到包括钉钉在内的通知渠道并更时间戳防死循环  # noqa: E501
                                await asyncio.to_thread(_mark_triggered, sub["id"], now)
                                err_msg = f"🚨 [智能选股报错] 任务 '{sub['name']}' 连续 {max_retries} 次执行失败！\n\n异常详情: {inner_e}"  # noqa: E501
                                asyncio.create_task(notification_service.send_alert(err_msg))

                    await asyncio.sleep(2)  # 错峰请求

                # 💡 及时释放大对象：ORM 模型列表与多市场的海量 JSON 返回值
                subs_to_run = None
                results = None
                final_data = None

                # 每 60 秒轮询一次，确保不会错过任何分钟级别的触发
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Screener Daemon] 订阅任务守护进程异常: {e}")
                await asyncio.sleep(30)

    async def daily_market_summary_daemon(self) -> None:
        """后台任务：每天 16:00 自动盘点全市场最强概念股并推送到 Telegram/通知渠道"""
        while True:
            try:
                now = datetime.now()
                # 每天 16:00 准时执行 (若在海外服务器部署，请自行根据 UTC 偏置调整小时数)  # noqa: E501
                if now.hour == 16 and now.minute == 0:
                    # 💡 分布式锁：选出唯一 Leader 节点执行，防止多服务器重复推送报告
                    lock_key = f"quant:lock:daily_summary:{now.strftime('%Y%m%d')}"
                    if not await redis_client.set(lock_key, "1", nx=True, ex=3600):
                        await asyncio.sleep(60)
                        continue

                    print("🚀 [Screener Daemon] 开始执行每日 16:00 最强概念股盘点...")

                    # 1. 设定底层扫盘策略: 涨幅>5%, 成交额>1亿, 换手率>2%
                    json_payload = json.dumps(
                        {
                            "dsl_display": "market:hk,sh,sz,us exclude_st:true change:>5 turnover:>100M turnover_rate:>2",  # noqa: E501
                            "markets": ["HK", "SH", "SZ", "US"],
                            "exclude_st": True,
                            "filters": [
                                {
                                    "field": "PRICE_CHANGE_PCT",
                                    "type": "accumulate",
                                    "min_value": 0.05,
                                },  # noqa: E501
                                {
                                    "field": "AVG_TURNOVER",
                                    "type": "accumulate",
                                    "min_value": 100000000.0,
                                },  # noqa: E501
                                {
                                    "field": "TURNOVER_RATIO",
                                    "type": "accumulate",
                                    "min_value": 0.02,
                                },  # noqa: E501
                            ],
                        }
                    )
                    markets, futu_filters, post_filters = self.parse_dsl_to_futu_filters(json_payload)  # noqa: E501

                    tasks = [futu_service.screen_stocks(market=m, filters=futu_filters) for m in markets]  # type: ignore  # noqa: E501
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    final_data = []
                    for res in results:
                        if isinstance(res, dict) and res.get("status") == "success":
                            final_data.extend(res.get("data", []))

                    # 内存二次过滤
                    if post_filters.get("exclude_st"):
                        final_data = [
                            r
                            for r in final_data
                            if "ST" not in r.get("name", "").upper() and "退" not in r.get("name", "")
                        ]  # noqa: E501

                    if final_data:
                        # 排序：按涨跌幅降序
                        final_data.sort(
                            key=lambda x: x.get("change_rate", 0) if x.get("change_rate") is not None else 0,
                            reverse=True,
                        )  # noqa: E501
                        top_stocks = final_data[:20]  # 截取前 20 只绝对龙头

                        # 2. 调用大模型进行主线概念总结

                        stocks_info = "\n".join(
                            [
                                f"- {r.get('name', '')} ({r.get('symbol', '')}): 涨跌幅 {r.get('change_rate', 0):.2f}%, 换手率 {r.get('turnover_rate', 0):.2f}%, 成交额 {r.get('turnover', 0) / 1e8:.2f}亿"
                                for r in top_stocks
                            ]
                        )  # noqa: E501

                        prompt = f"""你是一个顶尖的华尔街量化分析师。以下是今天全市场（A股、港股、美股）扫描出的量价齐升、资金抢筹的最强标的 Top 20：\n\n{stocks_info}\n\n请你根据这些股票的名称、行业属性和近期的宏观/科技趋势，用毒舌且专业的风格，写一份简短的《16:00 强势股复盘报告》。\n要求：\n1. 提取出 1-2 个今天最核心的炒作概念/主线。\n2. 点评几个最具代表性的龙头股。\n3. 提示追高风险或资金接盘情况。\n4. 格式使用清晰的 Markdown，字数控制在 400 字以内。"""  # noqa: E501

                        try:
                            resp = await llm_service.get_client().chat.completions.create(
                                model=llm_service.get_model(),
                                temperature=0.7,
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "你是一个资深量化交易主脑。",
                                    },
                                    {"role": "user", "content": prompt},
                                ],
                            )  # noqa: E501
                            content = resp.choices[0].message.content
                            report = content.strip() if content else ""

                            # 剔除可能包含的大模型包裹标记 (如 ```... ```)
                            report = re.sub(r"^```[a-zA-Z]*\n", "", report)
                            report = re.sub(r"\n```$", "", report)
                            report = report.strip()

                            # 3. 通过 Notification Tool 广发放通知
                            await notification_service.send_alert(f"🔥 [Quant Agent] 每日强势股主线复盘\n\n{report}")  # noqa: E501
                        except Exception as e:
                            print(f"⚠️ [Screener Daemon] LLM 总结失败: {e}")

                    # 💡 及时释放大对象：全市场扫盘的 JSON 结果体积巨大，防止在休眠期内驻留内存  # noqa: E501
                    results = None
                    final_data = None
                    top_stocks = None

                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Screener Daemon] 强势股盘点任务异常: {e}")
                await asyncio.sleep(30)

    async def clean_obsolete_knowledge_base_daemon(self) -> None:
        """后台任务：每天凌晨 00:00 按分类 TTL 清理 PG 知识库中的陈旧网页向量"""  # noqa: E501
        while True:
            try:
                now = datetime.now()
                if now.hour == 0 and now.minute == 0:
                    lock_key = f"quant:lock:clean_kb:{now.strftime('%Y%m%d')}"
                    if not await redis_client.set(lock_key, "1", nx=True, ex=3600):
                        await asyncio.sleep(60)
                        continue

                    print("🧹 [Knowledge Base Daemon] 开始按分类 TTL 清理 PG 知识库...")

                    def _do_clean():
                        import time

                        from sqlalchemy import text

                        try:
                            now_ts = int(time.time())
                            total_deleted = 0
                            with engine.begin() as conn:
                                table_exists = conn.execute(
                                    text(
                                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'webpage_knowledge_base')"
                                    )
                                ).scalar()
                                if not table_exists:
                                    return
                                # 按分类分别清理
                                for category, ttl_seconds in self.CATEGORY_TTL.items():
                                    cutoff_ts = now_ts - ttl_seconds
                                    res = conn.execute(
                                        text(
                                            "DELETE FROM webpage_knowledge_base "
                                            "WHERE category = :cat AND timestamp < :cutoff"
                                        ),
                                        {"cat": category, "cutoff": cutoff_ts},
                                    )
                                    total_deleted += res.rowcount
                                # 兜底：category 为 NULL 的记录按 general TTL 清理
                                cutoff_general = now_ts - self.CATEGORY_TTL["general"]
                                res = conn.execute(
                                    text(
                                        "DELETE FROM webpage_knowledge_base "
                                        "WHERE category IS NULL AND timestamp < :cutoff"
                                    ),
                                    {"cutoff": cutoff_general},
                                )
                                total_deleted += res.rowcount
                            print(
                                f"✅ [Knowledge Base Daemon] 分类 TTL 清理完成！共删除 {total_deleted} 个陈旧网页碎片块。"
                            )
                        except Exception as e:
                            print(f"⚠️ [Knowledge Base Daemon] 知识库清理失败: {e}")

                    await asyncio.to_thread(_do_clean)
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"⚠️ [Knowledge Base Daemon] 清理任务异常: {e}")
                await asyncio.sleep(30)
