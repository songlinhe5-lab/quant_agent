"""
MRKT-03: 市场复盘定时触发器

按各市场收盘后定时触发复盘生成：
- A股: 15:30 CST (07:30 UTC)
- 港股: 16:30 HKT (08:30 UTC)
- 美股: 04:30 UTC (美股收盘后)

通过环境变量 MRKT_SCHEDULE_ENABLED 控制是否启用（默认 true）。
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from backend.services.market_review.generator import generate_market_review
from backend.services.market_review.models import MarketType

# ── 调度配置 (UTC 时间) ─────────────────────────────────────────────────────
# 格式: (MarketType, hour, minute)
_SCHEDULE: list[tuple[MarketType, int, int]] = [
    (MarketType.A_SHARE, 7, 30),  # 15:30 CST = 07:30 UTC
    (MarketType.HK, 8, 30),  # 16:30 HKT = 08:30 UTC
    (MarketType.US, 4, 30),  # 美股收盘后 04:30 UTC
]

# 检查间隔 (秒)
_CHECK_INTERVAL = 60

# 防重复触发窗口 (秒): 同一市场同一天只触发一次
_DEDUP_WINDOW = 3600


def is_enabled() -> bool:
    """是否启用定时复盘"""
    return os.getenv("MRKT_SCHEDULE_ENABLED", "true").lower() == "true"


async def market_review_scheduler_daemon():
    """
    定时复盘守护进程。

    每分钟检查一次当前 UTC 时间，匹配调度表则触发对应市场的复盘生成。
    使用 Redis 键做防重复触发（同一天同一市场只生成一次）。
    """
    if not is_enabled():
        print("  [MRKT Scheduler] 已禁用 (MRKT_SCHEDULE_ENABLED=false)")
        return

    print("  [MRKT Scheduler] 启动，调度表:")
    for market, h, m in _SCHEDULE:
        print(f"    - {market.value}: {h:02d}:{m:02d} UTC")

    from backend.core.redis_client import redis_client

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_hm = (now.hour, now.minute)
            today_str = now.strftime("%Y-%m-%d")

            for market, sched_h, sched_m in _SCHEDULE:
                if current_hm != (sched_h, sched_m):
                    continue

                # 防重复: Redis SETNX，TTL 1小时
                dedup_key = f"quant:market_review:triggered:{market.value}:{today_str}"
                was_set = await redis_client.set(dedup_key, "1", nx=True, ex=_DEDUP_WINDOW)
                if not was_set:
                    continue  # 今天已触发过

                print(f"  [MRKT Scheduler] 触发 {market.value} {today_str} 复盘生成...")
                try:
                    review = await generate_market_review(market=market, date=today_str)
                    print(
                        f"  [MRKT Scheduler] ✅ {market.value} 复盘完成: "
                        f"风格={review.style}, 情绪={review.sentiment_score}"
                    )
                except Exception as e:
                    print(f"  [MRKT Scheduler] ❌ {market.value} 复盘失败: {e}")
                    # 失败时删除 dedup key，允许下次重试
                    await redis_client.delete(dedup_key)

        except asyncio.CancelledError:
            print("  [MRKT Scheduler] 收到取消信号，退出")
            break
        except Exception as e:
            print(f"  [MRKT Scheduler] 调度循环异常: {e}")

        await asyncio.sleep(_CHECK_INTERVAL)
