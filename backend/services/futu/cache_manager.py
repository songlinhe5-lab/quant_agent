"""
Futu 缓存管理模块
统一管理所有 L1 内存缓存和数据压缩工具
"""
import asyncio
from typing import Any, Dict, Optional, Tuple


class CacheManager:
    """缓存管理器 - 统一管理所有 Futu 数据缓存"""

    def __init__(self):
        # 订阅主题追踪
        self.subscribed_topics = set()

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
            compressed.append({
                "option_code": str(row.get('code', '')),
                "option_type": str(row.get('option_type', '')),
                "strike_price": safe_float(row.get('strike_price', 0.0))
            })
        return {
            "status": "success",
            "expiration_date": target_date,
            "count": len(compressed),
            "options": compressed,
            "message": "已返回截断后的期权链。大模型可使用 option_code 调用行情工具获取实时价格与希腊字母。"  # noqa: E501
        }

    @staticmethod
    def compress_quote_data(row) -> Dict[str, Any]:
        """压缩行情数据，提取核心字段"""
        from backend.core.utils import safe_divide, safe_float

        last_price = safe_float(row.get('last_price', 0.0))
        prev_close = safe_float(row.get('prev_close_price', 0.0))
        change_pct = safe_divide(last_price - prev_close, prev_close) * 100
        volume = safe_float(row.get('volume', 0))

        vol_str = f"{volume / 1e9:.2f}B" if volume >= 1e9 else \
                  f"{volume / 1e6:.2f}M" if volume >= 1e6 else \
                  f"{volume / 1e3:.2f}K" if volume >= 1e3 else str(volume)

        data = {
            "status": "success",
            "source": "futu",
            "ticker": str(row.get('code', '')),
            "last_price": last_price,
            "change_pct": f"{change_pct:+.2f}%",
            "volume": volume,
            "volume_str": vol_str,
            "turnover_rate": f"{safe_float(row.get('turnover_rate', 0.0)):.2f}%",
        }

        # 动态提取期权特有字段
        option_fields = {
            'strike_price': 'strike_price',
            'option_implied_volatility': 'implied_volatility',
            'option_delta': 'delta',
            'option_gamma': 'gamma',
            'option_vega': 'vega',
            'option_theta': 'theta'
        }
        for futu_col, standard_col in option_fields.items():
            val = row.get(futu_col)
            if val is not None and str(val).lower() not in ['nan', 'n/a', 'none']:
                data[standard_col] = safe_float(val)

        return data
