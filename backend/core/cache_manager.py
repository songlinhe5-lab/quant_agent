"""统一缓存清理工具。

集中管理「业务缓存」清理，避免误删交易态数据（活动挂单 / 持仓 / OMS 状态）。

设计约束：
- 清理动作只针对行情 / K 线 / 新闻 / 宏观 / insider 等业务缓存。
- 受保护前缀（交易态）即使被显式传入也会被跳过，杜绝误清导致实盘状态丢失。
"""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from backend.core.redis_client import redis_client

logger = logging.getLogger(__name__)

# 受保护前缀：下单/持仓/OMS 状态等交易态数据，清理时绝不触碰
PROTECTED_PREFIXES: Sequence[str] = (
    "quant:oms:active_orders",
    "quant:oms:status",
    "quant:oms:positions",
)

# 默认清理的业务缓存前缀（行情 / K线 / 新闻 / 宏观 / insider 等）
DEFAULT_CACHE_PREFIXES: Sequence[str] = (
    "quant:kline:*",
    "quant:cache:*",
    "quant:news:*",
    "quant:macro:*",
    "quant:insider*",
    "yf_macro_cache_*",
)


def _decode(key) -> str:
    if isinstance(key, bytes):
        return key.decode("utf-8", "ignore")
    return str(key)


def _is_protected(key: str) -> bool:
    return any(key.startswith(p) for p in PROTECTED_PREFIXES)


async def clear_cache(prefixes: Optional[List[str]] = None) -> int:
    """按前缀模式清理 Redis 缓存 key，返回清理的 key 数量。

    受保护前缀（交易态）即使被显式传入也会被跳过。
    """
    patterns = list(prefixes) if prefixes else list(DEFAULT_CACHE_PREFIXES)
    total = 0
    for raw in patterns:
        pattern = raw if "*" in raw else f"{raw}*"
        cursor = 0
        while True:
            try:
                cursor, keys = await redis_client.scan(cursor, match=pattern, count=200)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[CacheManager] 扫描前缀 {pattern} 失败: {e}")
                break
            if keys:
                safe = [k for k in keys if not _is_protected(_decode(k))]
                if safe:
                    try:
                        await redis_client.delete(*safe)
                        total += len(safe)
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"[CacheManager] 删除前缀 {pattern} 失败: {e}")
            if cursor == 0:
                break
    logger.info(f"[CacheManager] 清理缓存完成，共删除 {total} 个 key")
    return total
