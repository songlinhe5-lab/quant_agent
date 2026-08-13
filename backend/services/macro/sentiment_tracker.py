import asyncio
import json
import time

from backend.core import models
from backend.core.database import SessionLocal
from backend.core.redis_client import redis_client


class SentimentTracker:
    async def _run_once(self) -> bool:
        """执行一次情绪指标采集与落库。

        Returns:
            True  —— 已获取分布式锁（无论落库成功或失败，均由 daemon 按每小时频率调度）
            False —— 未获取到分布式锁（由 daemon 短暂休眠后重试本轮）
        """
        # 💡 分布式锁：防止多服务器部署时，每小时重复写入多条相同的数据记录
        lock_key = f"quant:lock:sentiment_tracker:{int(time.time() / 3600)}"
        if not await redis_client.set(lock_key, "1", nx=True, ex=1800):
            return False

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

            # ── 数据完整性红线 (PROD-零幻觉) ──
            # 若 VIX 与 P/C 源数据均缺失（如 yfinance 节点瘫痪导致 Redis 无缓存），
            # 禁止写入全 None 的垃圾记录污染历史序列，直接跳过本次打点。
            if vix_val is None and cpc_val is None:
                print("⚠️ [Sentiment Tracker] VIX/P-C 源数据均缺失，跳过本次打点（不写 None 记录，避免污染历史序列）")
                return True

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

        return True

    async def track_daemon(self):
        """后台守护进程：定时记录情绪指标到数据库，形成长期趋势曲线"""
        print("🚀 [Sentiment Tracker] 启动情绪风向标长期追踪记录任务...")

        # 延迟 30 秒启动，确保 yf_service 已经完成了首次的数据拉取并存入了 Redis
        await asyncio.sleep(30)

        while True:
            if not await self._run_once():
                # 未获取分布式锁，短暂休眠后重试本轮
                await asyncio.sleep(60)
                continue

            # 打点频率：每小时执行一次 (可根据需求改为每天执行，比如 86400 秒)
            await asyncio.sleep(3600)


sentiment_tracker = SentimentTracker()
