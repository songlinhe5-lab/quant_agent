"""IV 历史序列服务 (OPTION-04)。

仅持久化由真实行情计算出的 ATM IV，禁止任何模拟/伪造数据写入。
设计:
- 每次 /iv-rank 命中时惰性写入一条快照 (lazy persistence)，同时供
  周期性 daemon 批量扫描观察列表补点；
- 读取优先走 Redis 缓存 (quant:ivhistory:{ticker})，未命中回源 DB；
- 历史窗口默认 400 天，足以支撑 IV Rank / IV Percentile 计算。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.core.database import SessionLocal
from backend.core.models import IVSnapshot
from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

REDIS_KEY_PREFIX = "quant:ivhistory:"
# Redis 中保留的最大快照条数 (防止无限增长)
MAX_REDIS_POINTS = 800
# 单标的 DB 历史窗口 (天)
HISTORY_WINDOW_DAYS = 400
DB_LIMIT = 500


async def record_iv_snapshot(ticker: str, iv_value: float) -> None:
    """将一条真实 ATM IV 快照落库并写入 Redis 缓存。

    Args:
        ticker: 标的代码 (统一大写)
        iv_value: 小数形式的 IV, 0.25 = 25%
    """
    if iv_value is None or not isinstance(iv_value, (int, float)) or iv_value <= 0:
        return  # 不写入无效/负值, 防止污染历史序列
    t = ticker.upper()
    try:
        with SessionLocal() as db:
            db.add(IVSnapshot(ticker=t, iv_value=float(iv_value)))
            db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[IVHistory] 落库失败 {t}: {e}")
        return
    # Redis 追加 (list, 保持时间序); 失败不影响主流程
    try:
        key = f"{REDIS_KEY_PREFIX}{t}"
        await redis_client.rpush(key, str(iv_value))
        await redis_client.ltrim(key, -MAX_REDIS_POINTS, -1)
        await redis_client.expire(key, 60 * 60 * 24 * 30)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[IVHistory] Redis 写缓存失败 {t}: {e}")


async def get_iv_history(
    ticker: str,
    days: int = HISTORY_WINDOW_DAYS,
    limit: int = DB_LIMIT,
) -> list[float]:
    """读取某标的的真实 IV 历史序列 (升序)。

    优先 Redis 缓存；未命中则回源 DB 最近 `days` 天窗口。

    Returns:
        IV 数值列表 (小数), 例如 [0.21, 0.23, ...]
    """
    t = ticker.upper()
    # 1) Redis 缓存
    try:
        key = f"{REDIS_KEY_PREFIX}{t}"
        cached = await redis_client.lrange(key, 0, -1)
        if cached:
            vals = [float(x) for x in cached if x]
            if vals:
                return vals
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[IVHistory] Redis 读缓存失败 {t}: {e}")

    # 2) 回源 DB
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        with SessionLocal() as db:
            rows = (
                db.query(IVSnapshot.iv_value)
                .filter(IVSnapshot.ticker == t, IVSnapshot.recorded_at >= since)
                .order_by(IVSnapshot.recorded_at.asc())
                .limit(limit)
                .all()
            )
            return [float(r[0]) for r in rows]
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[IVHistory] DB 读历史失败 {t}: {e}")
        return []
