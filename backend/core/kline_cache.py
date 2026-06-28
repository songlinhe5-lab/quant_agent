"""
BE-02: 三级 K线缓存引擎

架构：
┌─────────────────────────────────────────────────────────────────┐
│  L1 Redis Hash (Hot)                                            │
│  ├─ TTL: 5 天                                                   │
│  ├─ 格式: Hash "quant:kline:{symbol}:{period}" → field=date     │
│  └─ 用途: 日内高频访问、实时图表渲染                               │
├─────────────────────────────────────────────────────────────────┤
│  L2 Parquet (Warm)                                              │
│  ├─ 保留: 1 年                                                  │
│  ├─ 格式: data/kline_warehouse/{period}/{symbol}.parquet        │
│  └─ 用途: 回测、技术分析、历史图表                                │
├─────────────────────────────────────────────────────────────────┤
│  L3 Object Storage (Cold) - 预留                                │
│  ├─ 保留: >1 年                                                 │
│  ├─ 格式: Cloudflare R2 / S3                                    │
│  └─ 用途: 长期归档、合规审计                                      │
└─────────────────────────────────────────────────────────────────┘

路由策略：
1. 查询最近 5 天 → L1 Redis（命中返回）
2. 查询 5 天 ~ 1 年 → L2 Parquet（命中返回，可选回填 L1）
3. 查询 >1 年 → L3（预留）或返回 L2 最早数据
4. 跨层查询 → 合并多层结果
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pandas as pd
import structlog

from backend.core.metrics import (
    KLINE_CACHE_HIT,
    KLINE_CACHE_QUERY_LATENCY,
)
from backend.core.redis_client import redis_client
from backend.services.kline_warehouse import kline_warehouse

logger = structlog.get_logger(__name__)


# ==========================================
#  缓存层级配置
# ==========================================

L1_TTL_DAYS = 5  # Redis 热缓存保留天数
L1_TTL_SECONDS = L1_TTL_DAYS * 86400
L2_RETENTION_DAYS = 365  # Parquet 温缓存保留天数
L1_KEY_PREFIX = "quant:kline"


class CacheTier:
    """缓存层级枚举"""

    L1_REDIS = "redis"
    L2_PARQUET = "parquet"
    L3_OBJECT = "object"
    MISS = "miss"


class KlineCacheEngine:
    """
    三级 K线缓存路由引擎

    使用示例：
        engine = KlineCacheEngine()

        # 获取 K线（自动路由到最优层级）
        df = await engine.get_kline("US.AAPL", "K_DAY", days=30)

        # 强制从指定层级获取
        df = await engine.get_kline("US.AAPL", "K_DAY", days=30, tier=CacheTier.L2_PARQUET)

        # 写入缓存（自动写入所有层级）
        await engine.put_kline("US.AAPL", "K_DAY", df)
    """  # noqa: E501

    def __init__(self):
        self._warehouse = kline_warehouse
        self._redis = redis_client

    async def get_kline(
        self,
        symbol: str,
        period: str = "K_DAY",
        days: int = 30,
        tier: Optional[str] = None,
        fill_l1: bool = True,
    ) -> Optional[pd.DataFrame]:
        """
        获取 K线数据（智能路由）

        Args:
            symbol: 标的代码（如 "US.AAPL"）
            period: K线周期（"K_DAY", "K_60M" 等）
            days: 获取最近 N 天数据
            tier: 强制指定缓存层级（None=自动路由）
            fill_l1: 从 L2/L3 获取后是否回填 L1

        Returns:
            K线 DataFrame 或 None
        """
        _t0 = time.perf_counter()

        # 自动路由策略
        if tier is None:
            if days <= L1_TTL_DAYS:
                tier = CacheTier.L1_REDIS
            elif days <= L2_RETENTION_DAYS:
                tier = CacheTier.L2_PARQUET
            else:
                tier = CacheTier.L3_OBJECT

        df = None
        hit_tier = CacheTier.MISS

        # L1: Redis 热缓存
        if tier == CacheTier.L1_REDIS:
            df = await self._get_l1(symbol, period, days)
            if df is not None:
                hit_tier = CacheTier.L1_REDIS
            else:
                # L1 miss → 降级到 L2
                df = await self._get_l2(symbol, period, days)
                if df is not None:
                    hit_tier = CacheTier.L2_PARQUET
                    if fill_l1:
                        asyncio.create_task(self._fill_l1(symbol, period, df))

        # L2: Parquet 温缓存
        elif tier == CacheTier.L2_PARQUET:
            df = await self._get_l2(symbol, period, days)
            if df is not None:
                hit_tier = CacheTier.L2_PARQUET
                if fill_l1 and days <= L1_TTL_DAYS:
                    asyncio.create_task(self._fill_l1(symbol, period, df))

        # L3: 对象存储（预留）
        elif tier == CacheTier.L3_OBJECT:
            df = await self._get_l3(symbol, period, days)
            if df is not None:
                hit_tier = CacheTier.L3_OBJECT

        # 记录指标
        latency = time.perf_counter() - _t0
        KLINE_CACHE_HIT.labels(tier=hit_tier).inc()
        KLINE_CACHE_QUERY_LATENCY.labels(tier=hit_tier).observe(latency)

        if df is not None:
            logger.debug(
                f"[K线缓存] {symbol} {period} {days}d → {hit_tier} "
                f"({len(df)} rows, {latency:.3f}s)"
            )
        else:
            logger.warning(f"[K线缓存] {symbol} {period} {days}d → MISS")

        return df

    async def put_kline(
        self,
        symbol: str,
        period: str,
        df: pd.DataFrame,
    ) -> None:
        """
        写入 K线数据到所有缓存层级

        Args:
            symbol: 标的代码
            period: K线周期
            df: K线 DataFrame
        """
        if df is None or df.empty:
            return

        # L1: Redis
        await self._put_l1(symbol, period, df)

        # L2: Parquet（通过 warehouse）
        # 注意：warehouse 有自己的增量更新逻辑，这里不重复实现
        # 调用方应该在更新 warehouse 后，再调用此方法同步到 L1

    # ── L1 Redis 操作 ─────────────────────────────────────────────

    async def _get_l1(
        self, symbol: str, period: str, days: int
    ) -> Optional[pd.DataFrame]:  # noqa: E501
        """从 Redis 获取 K线"""
        try:
            key = f"{L1_KEY_PREFIX}:{symbol}:{period}"
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            # 获取 Hash 中所有字段
            data = await self._redis.hgetall(key)
            if not data:
                return None

            # 解析并过滤时间范围
            records = []
            for date_str, json_str in data.items():
                if isinstance(date_str, bytes):
                    date_str = date_str.decode("utf-8")
                if isinstance(json_str, bytes):
                    json_str = json_str.decode("utf-8")

                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
                        tzinfo=timezone.utc
                    )  # noqa: E501
                    if dt >= cutoff:
                        record = json.loads(json_str)
                        record["time"] = date_str
                        records.append(record)
                except (ValueError, json.JSONDecodeError):
                    continue

            if not records:
                return None

            df = pd.DataFrame(records)
            df["time"] = pd.to_datetime(df["time"])
            df = df.sort_values("time").tail(days * 2)  # 多取一些以防节假日

            return df

        except Exception as e:
            logger.error(f"[K线缓存 L1] 读取 {symbol} 失败: {e}")
            return None

    async def _put_l1(self, symbol: str, period: str, df: pd.DataFrame) -> None:
        """写入 K线到 Redis"""
        try:
            key = f"{L1_KEY_PREFIX}:{symbol}:{period}"

            # 只保留最近 L1_TTL_DAYS 天的数据
            cutoff = datetime.now(timezone.utc) - timedelta(days=L1_TTL_DAYS)
            df = df.copy()
            df["time"] = pd.to_datetime(df["time"])
            df = df[df["time"] >= cutoff]

            if df.empty:
                return

            # 批量写入 Hash
            pipe = self._redis.pipeline()
            for _, row in df.iterrows():
                date_str = row["time"].strftime("%Y-%m-%d")
                record = {
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": float(row.get("volume", 0)),
                }
                pipe.hset(key, date_str, json.dumps(record))

            # 设置 TTL
            pipe.expire(key, L1_TTL_SECONDS)
            await pipe.execute()

            logger.debug(f"[K线缓存 L1] 写入 {symbol} {period} ({len(df)} rows)")

        except Exception as e:
            logger.error(f"[K线缓存 L1] 写入 {symbol} 失败: {e}")

    async def _fill_l1(self, symbol: str, period: str, df: pd.DataFrame) -> None:
        """回填 L1 缓存"""
        await self._put_l1(symbol, period, df)

    # ── L2 Parquet 操作 ────────────────────────────────────────────

    async def _get_l2(
        self, symbol: str, period: str, days: int
    ) -> Optional[pd.DataFrame]:  # noqa: E501
        """从 Parquet 获取 K线"""
        try:
            df = await self._warehouse.get_history(symbol, ktype=period, num=days)
            return df
        except Exception as e:
            logger.error(f"[K线缓存 L2] 读取 {symbol} 失败: {e}")
            return None

    # ── L3 对象存储操作（预留）────────────────────────────────────

    async def _get_l3(
        self, symbol: str, period: str, days: int
    ) -> Optional[pd.DataFrame]:  # noqa: E501
        """
        从对象存储获取 K线（预留接口）

        TODO: 实现 Cloudflare R2 / S3 对接
        """
        logger.info(f"[K线缓存 L3] {symbol} {period} - 对象存储尚未实现，返回 None")
        return None

    # ── 缓存管理 ──────────────────────────────────────────────────

    async def invalidate(self, symbol: str, period: str = None) -> None:
        """
        清除指定标的缓存

        Args:
            symbol: 标的代码
            period: K线周期（None=清除所有周期）
        """
        try:
            if period:
                key = f"{L1_KEY_PREFIX}:{symbol}:{period}"
                await self._redis.delete(key)
            else:
                # 清除所有周期
                pattern = f"{L1_KEY_PREFIX}:{symbol}:*"
                cursor = 0
                while True:
                    cursor, keys = await self._redis.scan(
                        cursor, match=pattern, count=100
                    )  # noqa: E501
                    if keys:
                        await self._redis.delete(*keys)
                    if cursor == 0:
                        break

            logger.info(f"[K线缓存] 已清除 {symbol} 缓存")

        except Exception as e:
            logger.error(f"[K线缓存] 清除 {symbol} 失败: {e}")

    async def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            # 统计 L1 键数量
            pattern = f"{L1_KEY_PREFIX}:*"
            count = 0
            cursor = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                count += len(keys)
                if cursor == 0:
                    break

            return {
                "l1_redis_keys": count,
                "l1_ttl_days": L1_TTL_DAYS,
                "l2_retention_days": L2_RETENTION_DAYS,
                "l3_enabled": False,
            }

        except Exception as e:
            logger.error(f"[K线缓存] 获取统计失败: {e}")
            return {"error": str(e)}


# ── 全局单例 ──────────────────────────────────────────────────────
_kline_cache_engine: Optional[KlineCacheEngine] = None


def get_kline_cache_engine() -> KlineCacheEngine:
    """获取 K线缓存引擎单例"""
    global _kline_cache_engine
    if _kline_cache_engine is None:
        _kline_cache_engine = KlineCacheEngine()
    return _kline_cache_engine
