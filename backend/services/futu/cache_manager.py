"""
Futu 缓存管理模块
统一管理所有 L1 内存缓存和数据压缩工具
"""

import asyncio
import os
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Set, Tuple

# 💡 内存安全防御：各缓存 TTL (秒)
_QUOTE_TTL = 30  # 行情快照 30 秒
_HISTORY_TTL = 3600  # K线 1 小时
_OPTION_TTL = 300  # 期权链 5 分钟
_FUND_FLOW_TTL = 120  # 资金流向 2 分钟
_ORDER_BOOK_TTL = 30  # 盘口 30 秒
_FUNDAMENTAL_TTL = 86400  # 基本面 24 小时
_MAX_CACHE_SIZE = 200  # 单类缓存最大条目数


class CacheManager:
    """缓存管理器 - 统一管理所有 Futu 数据缓存 + LRU 订阅池"""

    def __init__(self):
        # LRU 订阅池: OrderedDict[(ticker, sub_type_str)] → last_access_time
        # 尾部 = 最近访问，头部 = 最久未访问
        self._sub_pool: OrderedDict[Tuple[str, str], float] = OrderedDict()
        self.max_subscriptions = int(os.getenv("FUTU_MAX_SUBSCRIPTIONS", "100"))

        # 待退订队列：LRU 淘汰后放入，由调用方异步执行实际退订
        self._pending_unsub: Set[Tuple[str, str]] = set()

        # 各类数据缓存 {cache_key: (timestamp, data)}
        self._quote_cache: Dict[str, Tuple[float, Dict]] = {}
        self._history_cache: Dict[str, Tuple[float, Dict]] = {}
        self._option_chain_cache: Dict[str, Tuple[float, Dict]] = {}
        self._fund_flow_cache: Dict[str, Tuple[float, Dict]] = {}
        self._order_book_cache: Dict[str, Tuple[float, Dict]] = {}
        self._fundamental_cache: Dict[str, Tuple[float, Dict]] = {}

        # 资金流向限流与熔断
        self.ff_lock: Optional[asyncio.Lock] = None
        self.last_ff_time = 0.0
        self.ff_circuit_breaker_until = 0.0

    # ── LRU 订阅池管理 ─────────────────────────────────────────────

    @property
    def subscribed_topics(self) -> Set[Tuple[str, str]]:
        """兼容旧接口：返回当前所有已订阅的 (ticker, sub_type) 集合"""
        return set(self._sub_pool.keys())

    def touch_topic(self, ticker: str, sub_type: str) -> None:
        """标记订阅为最近访问（LRU 提升）"""
        key = (ticker, sub_type)
        if key in self._sub_pool:
            self._sub_pool.move_to_end(key)
        else:
            self._sub_pool[key] = time.time()

    def has_topic(self, ticker: str, sub_type: str) -> bool:
        """检查订阅是否存在并刷新 LRU"""
        key = (ticker, sub_type)
        if key in self._sub_pool:
            self._sub_pool.move_to_end(key)
            return True
        return False

    def remove_topic(self, ticker: str, sub_type: str) -> None:
        """手动移除订阅记录（退订后调用）"""
        self._sub_pool.pop((ticker, sub_type), None)

    def evict_lru(self, count: int = 1) -> list:
        """
        LRU 淘汰：弹出最久未使用的 count 个订阅。
        返回被剔除的 [(ticker, sub_type_str), ...] 列表，调用方需执行实际退订。
        """
        evicted = []
        for _ in range(count):
            if not self._sub_pool:
                break
            oldest_key, _ = self._sub_pool.popitem(last=False)
            evicted.append(oldest_key)
        return evicted

    def drain_pending_unsub(self) -> Set[Tuple[str, str]]:
        """取出并清空待退订队列"""
        result = self._pending_unsub.copy()
        self._pending_unsub.clear()
        return result

    def ensure_capacity(self, needed: int = 1) -> list:
        """
        确保订阅池有足够空间。如果当前数量 + needed > max，
        则淘汰最久未用的订阅，返回需要实际退订的列表。
        """
        evicted = []
        while len(self._sub_pool) + needed > self.max_subscriptions and self._sub_pool:
            oldest_key, _ = self._sub_pool.popitem(last=False)
            evicted.append(oldest_key)
            self._pending_unsub.add(oldest_key)
        return evicted

    @property
    def subscription_count(self) -> int:
        return len(self._sub_pool)

    def clear_all_subscriptions(self) -> None:
        """清空所有订阅记录（关闭连接时调用）"""
        self._sub_pool.clear()
        self._pending_unsub.clear()

    def evict_stale_cache(self):
        """内存安全防御：清理所有过期缓存，防止无界字典无限增长"""
        now = time.time()
        cache_configs = [
            (self._quote_cache, _QUOTE_TTL),
            (self._history_cache, _HISTORY_TTL),
            (self._option_chain_cache, _OPTION_TTL),
            (self._fund_flow_cache, _FUND_FLOW_TTL),
            (self._order_book_cache, _ORDER_BOOK_TTL),
            (self._fundamental_cache, _FUNDAMENTAL_TTL),
        ]
        for cache_dict, ttl in cache_configs:
            # 1. 清理过期条目
            stale = [k for k, (ts, _) in cache_dict.items() if now - ts > ttl]
            for k in stale:
                del cache_dict[k]
            # 2. 容量熔断：超过上限则清空最旧的一半
            if len(cache_dict) > _MAX_CACHE_SIZE:
                sorted_keys = sorted(cache_dict, key=lambda k: cache_dict[k][0])
                for k in sorted_keys[: len(sorted_keys) // 2]:
                    del cache_dict[k]

    # ── Quote Cache ───────────────────────────────────────────────

    def get_quote_cache(self, ticker: str) -> Optional[Tuple[float, Dict]]:
        return self._quote_cache.get(ticker)

    def set_quote_cache(self, ticker: str, timestamp: float, data: Dict):
        self._quote_cache[ticker] = (timestamp, data)

    # ── History Cache ─────────────────────────────────────────────

    def get_history_cache(self, key: str) -> Optional[Tuple[float, Dict]]:
        return self._history_cache.get(key)

    def set_history_cache(self, key: str, timestamp: float, data: Dict):
        self._history_cache[key] = (timestamp, data)

    # ── Option Chain Cache ────────────────────────────────────────

    def get_option_chain_cache(self, key: str) -> Optional[Tuple[float, Dict]]:
        return self._option_chain_cache.get(key)

    def set_option_chain_cache(self, key: str, timestamp: float, data: Dict):
        self._option_chain_cache[key] = (timestamp, data)

    # ── Fund Flow Cache ───────────────────────────────────────────

    def get_fund_flow_cache(self, key: str) -> Optional[Tuple[float, Dict]]:
        return self._fund_flow_cache.get(key)

    def set_fund_flow_cache(self, key: str, timestamp: float, data: Dict):
        self._fund_flow_cache[key] = (timestamp, data)

    # ── Order Book Cache ──────────────────────────────────────────

    def get_order_book_cache(self, key: str) -> Optional[Tuple[float, Dict]]:
        return self._order_book_cache.get(key)

    def set_order_book_cache(self, key: str, timestamp: float, data: Dict):
        self._order_book_cache[key] = (timestamp, data)

    # ── Fundamental Cache ─────────────────────────────────────────

    def get_fundamental_cache(self, key: str) -> Optional[Tuple[float, Dict]]:
        return self._fundamental_cache.get(key)

    def set_fundamental_cache(self, key: str, timestamp: float, data: Dict):
        self._fundamental_cache[key] = (timestamp, data)

    # ── Data Compression Tools ────────────────────────────────────

    @staticmethod
    def compress_chain_data(raw_df, target_date: str) -> Dict[str, Any]:
        """提取核心字段，并截断数据防止溢出"""
        from backend.core.utils import safe_float

        compressed = []
        for _, row in raw_df.head(60).iterrows():
            compressed.append(
                {
                    "option_code": str(row.get("code", "")),
                    "option_type": str(row.get("option_type", "")),
                    "strike_price": safe_float(row.get("strike_price", 0.0)),
                }
            )
        return {
            "status": "success",
            "expiration_date": target_date,
            "count": len(compressed),
            "options": compressed,
            "message": "已返回截断后的期权链。大模型可使用 option_code 调用行情工具获取实时价格与希腊字母。",  # noqa: E501
        }

    @staticmethod
    def compress_quote_data(row) -> Dict[str, Any]:
        """压缩行情数据，提取核心字段"""
        import logging

        from backend.core.utils import safe_divide, safe_float

        logger = logging.getLogger(__name__)

        # 调试: 打印所有可用字段 (仅首次)
        if not hasattr(CacheManager, "_lot_size_logged"):
            logger.info(f"[CacheManager] quote row keys: {list(row.keys()) if hasattr(row, 'keys') else 'N/A'}")
            CacheManager._lot_size_logged = True

        last_price = safe_float(row.get("last_price", 0.0))
        prev_close = safe_float(row.get("prev_close_price", 0.0))
        change_pct = safe_divide(last_price - prev_close, prev_close) * 100
        volume = safe_float(row.get("volume", 0))

        vol_str = (
            f"{volume / 1e9:.2f}B"
            if volume >= 1e9
            else f"{volume / 1e6:.2f}M"
            if volume >= 1e6
            else f"{volume / 1e3:.2f}K"
            if volume >= 1e3
            else str(volume)
        )

        # 尝试多种可能的 lot_size 字段名
        lot_size_raw = row.get("lot_size") or row.get("lotsize") or row.get("lot_Size") or 0
        lot_size = int(safe_float(lot_size_raw) or 0)
        if lot_size > 0 and not hasattr(CacheManager, f"_lot_size_logged_{row.get('code', '')}"):
            logger.info(f"[CacheManager] {row.get('code', 'unknown')} lot_size={lot_size} (raw={lot_size_raw})")
            setattr(CacheManager, f"_lot_size_logged_{row.get('code', '')}", True)

        data = {
            "status": "success",
            "source": "futu",
            "ticker": str(row.get("code", "")),
            "last_price": last_price,
            "change_pct": f"{change_pct:+.2f}%",
            "volume": volume,
            "volume_str": vol_str,
            "turnover_rate": f"{safe_float(row.get('turnover_rate', 0.0)):.2f}%",
            "lot_size": lot_size,
        }

        # 动态提取期权特有字段
        option_fields = {
            "strike_price": "strike_price",
            "option_implied_volatility": "implied_volatility",
            "option_delta": "delta",
            "option_gamma": "gamma",
            "option_vega": "vega",
            "option_theta": "theta",
        }
        for futu_col, standard_col in option_fields.items():
            val = row.get(futu_col)
            if val is not None and str(val).lower() not in ["nan", "n/a", "none"]:
                data[standard_col] = safe_float(val)

        return data
