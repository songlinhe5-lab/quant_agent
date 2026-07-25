import asyncio
import json
import time

from backend.core import models
from backend.core.database import SessionLocal
from backend.core.redis_client import redis_client


class SentimentTracker:
    async def track_daemon(self):
        """后台守护进程：定时记录情绪指标到数据库，形成长期趋势曲线"""
        print("🚀 [Sentiment Tracker] 启动情绪风向标长期追踪记录任务...")

        # 延迟 30 秒启动，确保 yf_service 已经完成了首次的数据拉取并存入了 Redis
        await asyncio.sleep(30)

        while True:
            # 💡 分布式锁：防止多服务器部署时，每小时重复写入多条相同的数据记录
            lock_key = f"quant:lock:sentiment_tracker:{int(time.time() / 3600)}"
            if not await redis_client.set(lock_key, "1", nx=True, ex=1800):
                await asyncio.sleep(60)
                continue

            try:
                # 1. 提取 VIX 恐慌指数
                vix_val = None
                vix_cache = await redis_client.get("yf_macro_cache_^VIX")
                if vix_cache:
                    records = json.loads(vix_cache)
                    if records and len(records) > 0:
                        v_val = records[-1].get("Close")
                        if v_val is None:
                            v_val = next(
                                (v for k, v in records[-1].items() if str(k).startswith("('Close'")),
                                None,
                            )  # noqa: E501
                        if v_val:
                            vix_val = round(float(v_val), 2)

                # 2. 提取 P/C Ratio
                cpc_val = None
                cpc_cache = await redis_client.get("yf_macro_cache_^CPC")
                if cpc_cache:
                    records = json.loads(cpc_cache)
                    if records and len(records) > 0:
                        c_val = records[-1].get("Close")
                        if c_val is None:
                            c_val = next(
                                (v for k, v in records[-1].items() if str(k).startswith("('Close'")),
                                None,
                            )  # noqa: E501
                        if c_val:
                            cpc_val = round(float(c_val), 2)

                # 3. 拟合 Credit Spread (基于 VIX)
                credit_spread = round(2.0 + (vix_val / 10.0), 2) if vix_val is not None else None  # noqa: E501

                # 4. 存入关系型数据库做持久化
                def save_to_db():
                    with SessionLocal() as db:
                        record = models.SentimentRecord(
                            vix_value=vix_val,
                            pc_ratio=cpc_val,
                            credit_spread=credit_spread,
                        )  # noqa: E501
                        db.add(record)
                        db.commit()

                await asyncio.to_thread(save_to_db)  # 数据库是同步 IO，必须用 to_thread 防止阻塞网关  # noqa: E501
                print(f"📈 [Sentiment Tracker] 数据打点成功: VIX={vix_val}, P/C={cpc_val}, Spread={credit_spread}")  # noqa: E501

            except Exception as e:
                print(f"❌ [Sentiment Tracker] 记录数据失败: {e}")

            # 打点频率：每小时执行一次 (可根据需求改为每天执行，比如 86400 秒)
            await asyncio.sleep(3600)


sentiment_tracker = SentimentTracker()
