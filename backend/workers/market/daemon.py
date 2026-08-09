"""
==========================================
Market Daemon - 仅 Master 运行的守护进程集合
==========================================
市场守护进程集合，包含多种数据源的后台监控任务：
- Finnhub: 新闻、财报、宏观、内幕交易
- AKShare: A股新闻、经济日历（通过跨节点路由）

确保 Slave 节点只负责数据采集，不启动任何 LLM/情感分析相关的守护进程。

守护进程列表:
  - _news_stream_daemon:            市场新闻轮询 + LLM 情感分析
  - _company_news_daemon:           个股新闻监控 + Pub/Sub 推送
  - macro_alert_daemon:             宏观核弹数据监控 + LLM 秒评（独立模块 workers/macro/alert_daemon.py）
  - _earnings_alert_daemon:         重磅财报监控 + LLM 秒评
  - _insider_transactions_marquee:  高管内幕交易跑马灯

> 2026-08-07 修订：Finnhub 仅远程。原 _trade_stream_daemon（WS tick 长连接）已移除，
> 所有 Finnhub 取数经 DataSourceRegistry → DataSourceRouter → data_subservice REST 快照，
> 主服务不再持有本地 FinnhubService / WS 订阅。
"""

import asyncio
import hashlib
import json
import os
import re
import time
from datetime import datetime
from typing import Dict

from backend.core.redis_client import l1_cached_redis, redis_client
from backend.core.utils import is_my_shard
from backend.services.datasource import Result
from backend.services.datasource.source_registry import datasource_registry
from backend.workers.macro.alert_daemon import macro_alert_daemon


async def _finnhub_fetch(action: str, **params):
    """经 DataSourceRegistry 主路径调用 Finnhub，返回 Result.data（list/dict）或 None。

    统一走 registry.fetch 以触发 call_metrics 真实计数（运维面板依赖此口径），
    禁止在守护进程中直连 FinnhubService 的 REST 方法，统一经 registry 远程取数，
    以免调用/延迟/限流统计丢失（BE-ARCH-01 边界约束）。
    """
    try:
        result: Result = await datasource_registry.fetch("finnhub", action, params)
    except Exception as exc:  # noqa: BLE001 - 守护进程容错，不中断轮询
        print(f"❌ [Finnhub Daemon] registry.fetch({action}) 异常: {exc}")
        return None
    if not getattr(result, "is_success", False):
        return None
    return getattr(result, "data", None)


async def run_global_daemon() -> None:
    """
    统一入口：合并启动与守护市场守护进程。

    设计原则 (2026-08-07): Finnhub 仅远程。所有 Finnhub 取数经 DataSourceRegistry
    (→ DataSourceRouter → data_subservice REST 快照) 完成，不再持有本地 FinnhubService
    / WS tick 订阅。_trade_stream_daemon 已移除（WS 订阅层冗余）。
    """
    await asyncio.gather(
        _news_stream_daemon(),
        _company_news_daemon(),
        macro_alert_daemon(),
        _insider_transactions_marquee_daemon(),
        _earnings_alert_daemon(),
        return_exceptions=True,
    )


# ==========================================
# 财报发布监控守护进程
# ==========================================
async def _earnings_alert_daemon():
    """
    后台守护进程：监控核心明星公司的财报发布，第一时间推送到通知渠道并由主脑进行点评
    """
    from backend.services.ai_narrator.llm_service import llm_service
    from backend.services.alert.notification import notification_service

    print("🚀 [Finnhub Daemon] 启动核心财报发布监控守护进程...")

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
        await asyncio.sleep(120)
        try:
            res = await _finnhub_fetch("earnings", days_ahead=1, skip_cache=True)
            if not res:
                continue

            earnings_list = res
            for row in earnings_list:
                symbol = str(row.get("symbol", "")).upper()
                if symbol not in core_symbols:
                    continue

                eps_actual = row.get("epsActual")
                rev_actual = row.get("revenueActual")

                if eps_actual is not None or rev_actual is not None:
                    eps_est = row.get("epsEstimate", "--")
                    rev_est = row.get("revenueEstimate", "--")
                    quarter = row.get("quarter", "--")
                    date_str = str(row.get("date", ""))

                    dedup_key = f"quant:earnings:notified:{date_str}:{symbol}"
                    is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400 * 3)

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
                                ai_comment = re.sub(r"^```[a-zA-Z]*\s*", "", ai_comment)
                                ai_comment = re.sub(r"\s*```$", "", ai_comment).strip()
                                ai_comment = f"\n\n🧠 [主脑财报秒评]: {ai_comment}"
                        except Exception as llm_e:
                            print(f"⚠️ [Finnhub Daemon] 财报大模型解读异常: {llm_e}")

                        def fmt_num(val):
                            if val in ("--", None, ""):
                                return "--"
                            try:
                                fval = float(val)
                                if fval >= 1e9:
                                    return f"{fval / 1e9:.2f}B"
                                if fval >= 1e6:
                                    return f"{fval / 1e6:.2f}M"
                                return str(val)
                            except Exception:
                                return str(val)

                        msg = f"🚨 [重磅财报出炉]\n\n🏢 巨头: {symbol} (Q{quarter})\n💵 实际 EPS: {eps_actual} (预期: {eps_est})\n💰 实际营收: {fmt_num(rev_actual)} (预期: {fmt_num(rev_est)}){ai_comment}\n\n⚠️ 财报已发布，盘前/盘后价格可能发生剧烈跳空，请注意期权 IV Crush 风险！"  # noqa: E501
                        await notification_service.send_alert(msg)
        except Exception as e:
            print(f"❌ [Finnhub Daemon] 财报报警监控异常: {e}")


# ==========================================
# 市场新闻轮询守护进程
# ==========================================
async def _news_stream_daemon() -> None:
    """后台守护进程：通过 Finnhub HTTP 接口准实时轮询市场新闻并推送到 Redis ZSET 与 Pub/Sub"""
    from backend.services.macro.sentiment_service import sentiment_service

    print("🚀 [Finnhub Daemon] 启动市场新闻轮询守护进程 (HTTP -> ZSET + Pub/Sub)...")
    # Finnhub 仅远程：API Key 由 data_subservice 持有，主服务不再直连。此处仅做能力探测。
    if not os.getenv("FINNHUB_API_KEY"):
        print("⚠️ [Finnhub Daemon] 未配置 FINNHUB_API_KEY，无法启动新闻监控。")
        return

    # 冷启动拉取初始快照
    try:
        print("🔄 [Finnhub Daemon] 正在通过 HTTP 拉取初始新闻快照以填充 ZSET...")
        init_res = await asyncio.wait_for(_finnhub_fetch("market_news", category="general"), timeout=15.0)
        if init_res:
            rules = await _get_news_tags_rules()
            new_items = []
            for news_item in reversed(init_res):
                headline = news_item.get("headline", "")
                if not headline:
                    continue
                headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()
                dedup_key = f"quant:news:dedup:{headline_hash}"
                is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)
                if is_new:
                    new_items.append(news_item)

            if new_items:
                print(f"🧠 [Finnhub Daemon] 正在调用 LLM 对 {len(new_items)} 条初始新闻进行情感分析与摘要生成...")
                scored_items = await sentiment_service.batch_analyze_news(new_items)
                for news_item in scored_items:
                    headline = news_item.get("headline", "")
                    text_content = f"{headline} {news_item.get('summary', '')}".lower()
                    news_item["tags"] = _generate_news_tags(text_content, rules)
                    ts = float(news_item.get("datetime", time.time()))
                    member = json.dumps(news_item, sort_keys=True)
                    await redis_client.zadd("macro_news_stream", {member: ts})
            print("✅ [Finnhub Daemon] 初始新闻快照填充完毕。")
    except asyncio.TimeoutError:
        print("⚠️ [Finnhub Daemon] 初始快照拉取超时 (15s)，跳过...")
    except Exception as e:
        print(f"⚠️ [Finnhub Daemon] 初始快照拉取异常: {e}")

    while True:
        await asyncio.sleep(60)
        try:
            res = await _finnhub_fetch("market_news", category="general")
            if res:
                news_items = res
                rules = await _get_news_tags_rules()
                new_incoming = []

                for news_item in reversed(news_items):
                    headline = news_item.get("headline", "")
                    if not headline:
                        continue
                    headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()
                    dedup_key = f"quant:news:dedup:{headline_hash}"
                    is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)
                    if is_new:
                        new_incoming.append(news_item)

                if new_incoming:
                    print(f"📡 [Finnhub Daemon] 轮询到 {len(new_incoming)} 条新新闻，交由 LLM 处理...")
                    for chunk in [new_incoming[i : i + 5] for i in range(0, len(new_incoming), 5)]:
                        scored_items = await sentiment_service.batch_analyze_news(chunk)
                        for news_item in scored_items:
                            headline = news_item.get("headline", "")
                            text_content = f"{headline} {news_item.get('summary', '')}".lower()
                            news_item["tags"] = _generate_news_tags(text_content, rules)
                            dt_val = news_item.get("datetime")
                            ts = float(dt_val) if dt_val is not None else time.time()
                            member = json.dumps(news_item, sort_keys=True)
                            await redis_client.zadd("macro_news_stream", {member: ts})
                            await redis_client.publish("macro_news", member)

                cutoff_time = time.time() - 86400
                await redis_client.zremrangebyscore("macro_news_stream", 0, cutoff_time)

                res = None
                news_items = None
                new_incoming = None
                chunk = None
                scored_items = None
        except Exception as e:
            print(f"❌ [Finnhub Daemon] 新闻轮询异常: {e}")


# ==========================================
# 个股新闻监控守护进程
# ==========================================
async def _company_news_daemon() -> None:
    """后台守护进程：个股新闻的伪长连接监控订阅"""
    print("🚀 [Finnhub Daemon] 启动个股新闻长链接监控守护进程...")
    while True:
        await asyncio.sleep(60)
        try:
            monitored_tickers = await redis_client.hkeys("quant:settings:monitored_refcounts")
            if not monitored_tickers:
                continue

            for raw_ticker in monitored_tickers:
                ticker = raw_ticker.decode("utf-8") if isinstance(raw_ticker, bytes) else str(raw_ticker)

                if not is_my_shard(ticker):
                    continue

                is_asian_stock = any(x in ticker.upper() for x in ["HK", "SH", "SZ"]) or ticker.isdigit()
                if is_asian_stock:
                    from backend.services.datasource.router import data_source_router

                    res = await data_source_router.fetch_akshare("news", ticker=ticker)
                else:
                    res = await _finnhub_fetch("company_news", ticker=ticker, days_back=3, skip_cache=True)

                if res:
                    news_items = res
                    new_incoming = []

                    for news_item in reversed(news_items):
                        headline = news_item.get("headline", "")
                        if not headline:
                            continue
                        headline_hash = hashlib.md5(headline.encode("utf-8")).hexdigest()
                        dedup_key = f"quant:news:dedup:company:{headline_hash}"
                        is_new = await redis_client.set(dedup_key, "1", nx=True, ex=86400)
                        if is_new:
                            new_incoming.append(news_item)

                    if new_incoming:
                        print(f"📡 [Finnhub Daemon] {ticker} 监控到 {len(new_incoming)} 条个股新闻！发布至通道...")
                        for item in new_incoming:
                            await redis_client.publish(f"live_company_news_{ticker}", json.dumps(item))

                await asyncio.sleep(2)

            monitored_tickers = None
            res = None
            news_items = None
            new_incoming = None
        except Exception as e:
            print(f"❌ [Finnhub Daemon] 个股新闻监控异常: {e}")


# ==========================================
# WebSocket 实时交易流守护进程（已移除，2026-08-07）
# ==========================================
# 原 _trade_stream_daemon（Finnhub WS tick 长连接）已删除：Finnhub 现仅经 DataSourceRouter
# 远程 REST 快照（data_subservice 持有 WS 订阅），主服务不再持有本地 FinnhubService / WS 订阅。
# quote 实时性由 data_subservice 经 Redis pubsub 回灌，主服务走 registry.fetch 即远程快照。


# ==========================================
# 宏观核弹数据监控守护进程（已独立至 backend/workers/macro/alert_daemon.py）
# 注意：原 _macro_alert_daemon 命名误导——其数据来自 AKShare + FRED，与 Finnhub 无关，
# 仅是寄生在 finnhub collector 启动树上。现独立化，不再依赖采集器开关启停。
# ==========================================


# ==========================================
# 高管内幕交易跑马灯守护进程
# ==========================================
async def _insider_transactions_marquee_daemon() -> None:
    """后台守护进程：定时获取核心标的的高管内幕交易，筛选后推送到 Redis ZSET 供前端跑马灯"""
    print("🚀 [Finnhub Daemon] 启动高管内幕交易跑马灯守护进程...")

    MAJOR_TICKERS = [
        "US.AAPL",
        "US.MSFT",
        "US.NVDA",
        "US.GOOG",
        "US.AMZN",
        "US.META",
        "US.TSLA",
        "HK.00700",
        "HK.09988",
        "US.AMD",
        "US.INTC",
    ]
    MARQUEE_KEY = "quant:insider_marquee"
    DEDUP_KEY = "quant:insider_dedup"

    while True:
        await asyncio.sleep(300)
        try:
            print(f"🔄 [Finnhub Daemon] 正在刷新 {len(MAJOR_TICKERS)} 个核心标的的高管内幕交易...")

            new_transactions_count = 0
            for ticker in MAJOR_TICKERS:
                res = await _finnhub_fetch("insider_trading", ticker=ticker, limit=5)

                if res:
                    transactions = res

                    for tx in transactions:
                        transaction_value = abs(tx.get("change", 0) * tx.get("transaction_price", 0))

                        if transaction_value >= 100000 or abs(tx.get("change", 0)) >= 10000:
                            tx_hash_data = {
                                "ticker": ticker,
                                "date": tx.get("date"),
                                "name": tx.get("name"),
                                "change": tx.get("change"),
                                "price": tx.get("transaction_price"),
                            }
                            tx_hash = hashlib.md5(json.dumps(tx_hash_data, sort_keys=True).encode("utf-8")).hexdigest()

                            tx_date_str = tx.get("date", "")
                            if not tx_date_str:
                                continue
                            try:
                                tx_date = datetime.strptime(tx_date_str, "%Y-%m-%d").date()
                                if (datetime.now().date() - tx_date).days > 3:
                                    continue
                                tx_datetime = datetime.combine(tx_date, datetime.min.time())
                                tx_timestamp = tx_datetime.timestamp()
                            except ValueError:
                                continue

                            is_new = await redis_client.set(f"{DEDUP_KEY}:{tx_hash}", "1", nx=True, ex=86400 * 7)
                            if is_new:
                                await redis_client.zadd(
                                    MARQUEE_KEY,
                                    {json.dumps(tx_hash_data): tx_timestamp},
                                )
                            new_transactions_count += 1

            if new_transactions_count > 0:
                print(f"✨ [Finnhub Daemon] 检测到 {new_transactions_count} 条新的显著高管交易，已推送到跑马灯队列。")
                await redis_client.zremrangebyrank(MARQUEE_KEY, 0, -101)

        except Exception as e:
            print(f"❌ [Finnhub Daemon] 高管内幕交易跑马灯监控异常: {e}")


# ==========================================
# 辅助函数
# ==========================================
async def _get_news_tags_rules() -> Dict[str, str]:
    """从 Redis 获取动态新闻打标规则"""
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
        "GEOPOLITICS": r"\b(war|geopolitical|military|israel|russia|ukraine|sanction|tariff)\b",
    }
    return default_rules


def _generate_news_tags(text_content: str, rules: Dict[str, str]) -> list:
    """根据动态规则生成宏观检索标签"""
    tags = set()
    for tag, pattern in rules.items():
        try:
            if re.search(pattern, text_content):
                tags.add(tag)
        except re.error:
            continue
    return list(tags)
