"""
宏观核弹数据监控守护进程（独立模块）

[架构红线 - DIST/ARCH]
本模块属于主服务的「业务编排层」（LLM 秒评 + 通知 + 宏观聚合），
依赖 backend 内部业务模块（ai_narrator / alert / macro / datasource router），
**不构成数据源获取逻辑**，故保留在主服务，不下沉 data_subservice。

原始 _macro_alert_daemon 寄生在 Finnhub collector 启动树上（命名误导，
实际数据来自 AKShare economic_calendar + FRED，与 Finnhub 无关）。
现独立为 workers/macro/alert_daemon.py，独立于采集器开关启停，默认常驻。
"""

import asyncio
import hashlib
import re

from backend.core.redis_client import redis_client


async def macro_alert_daemon() -> None:
    """后台守护进程：监控高危宏观事件，当数据实际公布时第一时间推送"""
    from backend.services.ai_narrator.llm_service import llm_service
    from backend.services.alert.notification import notification_service

    print("🚀 [Macro Daemon] 启动宏观日历出炉监控守护进程...")
    while True:
        await asyncio.sleep(60)
        try:
            from backend.services.datasource.router import data_source_router

            res = await data_source_router.fetch_akshare("economic_calendar", days_ahead=1)
            if res.get("status") == "error" or not res.get("data"):
                from backend.services.macro.fred_service import fred_service

                res = await fred_service.get_economic_calendar(days_ahead=1)

            if res.get("status") == "error" or not res.get("data"):
                continue

            events = res.get("data", [])
            for row in events:
                event_name = str(row.get("event", ""))
                impact = str(row.get("impact", "low")).lower()

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
                ]
                if any(k in event_name.lower() for k in high_impact_keywords):
                    impact = "high"

                if impact != "high":
                    continue

                actual_val = row.get("actual")
                if actual_val is not None:
                    estimate_val = row.get("estimate", "--")
                    previous_val = row.get("previous", "--")
                    country = row.get("country", "Global")

                    event_date = str(row.get("time", "")).split(" ")[0] if " " in str(row.get("time", "")) else "today"
                    dedup_key = (
                        f"quant:macro:notified:{event_date}:{hashlib.md5(event_name.encode('utf-8')).hexdigest()}"
                    )

                    is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)
                    if is_new:
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
                                ai_comment = re.sub(r"^```[a-zA-Z]*\s*", "", ai_comment)
                                ai_comment = re.sub(r"\s*```$", "", ai_comment).strip()
                                ai_comment = f"\n\n🧠 [主脑秒评]: {ai_comment}"
                        except Exception as llm_e:
                            print(f"⚠️ [Macro Daemon] 宏观数据大模型解读异常: {llm_e}")

                        msg = f"🚨 [宏观核弹数据出炉]\n\n📅 事件: {event_name}\n🇺🇳 国家: {country}\n🔴 公布值 (Actual): {actual_val}\n⚪ 预期值 (Forecast): {estimate_val}\n⚪ 前值 (Previous): {previous_val}{ai_comment}\n\n⚠️ 数据已发布，盘面可能出现剧烈波动，请注意风控！"  # noqa: E501
                        await notification_service.send_alert(msg)
        except Exception as e:
            print(f"❌ [Macro Daemon] 宏观报警监控异常: {e}")
