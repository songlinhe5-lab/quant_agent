"""
AkShareAdapter - 阿 share 数据源适配器

基于 DataSourcePort Protocol 实现的具体数据源 Adapter，负责从 AkShare 获取
港股、A 股的行情和资金流数据。

主要用途：
- Futu 无法覆盖的 A 股标的 (SH./SZ.前缀)
- 南向资金流向数据
- 作为 Futu 不可用时的降级方案

限制说明：
- HTTP 爬虫方式，限流风险极高 (建议配合 Redis 缓存)
- 数据延迟约 15-30 分钟
- 稳定性不如商业 API，建议仅用于兜底
"""

import time
from typing import Any, Dict, List, Optional

import akshare as ak

from backend.core.logger import logger

from .data_source_port import DataSourcePort, DataSourceResult


class AkShareAdapter(DataSourcePort):
    """
    AkShare 数据源适配器

    能力清单:
    - stock_quote: 实时/快照行情 (港股/A 股)
    - stock_history: 历史 K 线数据
    - hsgt_holders: 沪深港通/南向资金持股
    - hsgt_top10: 北向资金前十名持仓

    注意事项:
    - 免费 API，限流严格 (建议 RPM < 20)
    - 使用 HTTP 请求，可能需要代理 IP
    - 数据质量参差不齐，需做验证
    """

    # ===== 类常量 =====

    DEFAULT_RATE_LIMIT = 20  # 每分钟最多 20 次请求 (保守策略)
    CACHE_TTL_SECONDS = 300  # 行情缓存 5 分钟
    MAX_TIMEOUT_SECONDS = 10  # 请求超时

    def __init__(self, enable_cache: bool = True, cache_ttl: int = CACHE_TTL_SECONDS):
        """
        初始化 AkShareAdapter

        Args:
            enable_cache: 是否启用响应缓存 (默认 True)
            cache_ttl: 缓存过期时间 (秒)
        """
        self._name = "akshare"
        self._version = "1.0.0"
        self._enable_cache = enable_cache
        self._cache_ttl = cache_ttl

        # 缓存字典
        self._cache: Dict[str, dict] = {}

        # 速率限制计数器
        self._request_count = 0
        self._last_request_time: Optional[float] = None
        self._rate_limited_until: Optional[float] = None

    # ========== Protocol 必需属性实现 ==========

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def capabilities(self) -> List[str]:
        return ["stock_quote", "stock_history", "hsgt_holders", "hsgt_top10"]

    @property
    def is_available(self) -> bool:
        """检查 AkShare 是否可用"""
        if self._is_rate_limited:
            return False

        try:
            # 简单探测：尝试获取一个常用标的的数据
            result = ak.stock_zh_a_spot_em()
            return not result.empty
        except Exception:
            return False

    # ========== Protocol 必需方法实现 ==========

    def fetch(self, action: str, params: dict) -> DataSourceResult:
        """
        统一数据获取入口

        Args:
            action: 操作类型 (stock_quote/stock_history/hsgt_*)
            params: 参数字典

        Returns:
            DataSourceResult: 统一结果包装器
        """
        if action not in self.capabilities:
            return DataSourceResult.error(f"Unsupported action: {action}", source=self.name)

        # 检查限流
        if self._is_rate_limited:
            retry_after = self._rate_limited_until - time.time()
            return DataSourceResult.rate_limited(retry_after_seconds=max(1, int(retry_after)), source=self.name)

        try:
            start_time = time.time()

            if action == "stock_quote":
                result = self._fetch_stock_quote(params)
            elif action == "stock_history":
                result = self._fetch_stock_history(params)
            elif action == "hsgt_holders":
                result = self._fetch_hsgt_holders(params)
            elif action == "hsgt_top10":
                result = self._fetch_hsgt_top10(params)
            else:
                return DataSourceResult.error(f"Unknown action: {action}")

            latency_ms = (time.time() - start_time) * 1000

            # 更新请求计数
            self._record_request()

            # 包装结果
            return DataSourceResult(
                status="success" if result.get("success") else "error",
                data=result.get("data"),
                source="akshare",
                latency_ms=latency_ms,
                cached=result.get("cached", False),
                error=result.get("message") if not result.get("success") else None,
            )

        except Exception as e:
            return DataSourceResult.error(str(e), source=self.name)

    # ========== 内部私有方法 ==========

    @property
    def _is_rate_limited(self) -> bool:
        """检查是否处于限流窗口期"""
        if not self._rate_limited_until:
            return False

        return time.time() < self._rate_limited_until

    def _record_request(self):
        """记录一次请求，用于限流检测"""
        now = time.time()
        self._request_count += 1
        self._last_request_time = now

        # 简单的速率限制 (每分钟最多 20 次)
        if self._request_count >= self.DEFAULT_RATE_LIMIT:
            self._rate_limited_until = now + 60
            logger.warning("[AkShareAdapter] Rate limit reached, backing off for 60s")

    def _get_cached(self, key: str) -> Optional[Any]:
        """获取缓存数据"""
        if not self._enable_cache:
            return None

        cached = self._cache.get(key)
        if cached and time.time() < cached.get("expires_at", 0):
            return cached["data"]

        # 过期清理
        if cached:
            del self._cache[key]
        return None

    def _set_cache(self, key: str, data: Any):
        """设置缓存数据"""
        if not self._enable_cache:
            return

        self._cache[key] = {
            "data": data,
            "expires_at": time.time() + self._cache_ttl,
        }

    def _fetch_stock_quote(self, params: dict) -> dict:
        """
        获取实时行情 (港股/A 股)

        Args:
            params: {"ticker": "00700.HK"} 或 {"symbol": "sh600519"}

        Returns:
            dict: {"success": bool, "data": QuoteData, "message": str?}
        """
        ticker = params.get("ticker") or params.get("symbol")

        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}

        try:
            # 根据 ticker 格式选择接口
            if ticker.startswith("SH.") or ticker.startswith("SZ."):
                # A 股格式转换
                symbol = ticker.replace(".", "")
                df = ak.stock_zh_a_spot_em()
                df = df[df["代码"] == symbol]
            elif "." in ticker:
                # 港股格式 (如 00700.HK)
                code = ticker.split(".")[0]
                df = ak.stock_hk_spot_em()
                df = df[df["代码"] == code]
            else:
                return {"success": False, "message": "Unsupported ticker format"}

            if df.empty:
                return {"success": False, "message": "No data found for ticker"}

            row = df.iloc[0]
            quote_data = {
                "ticker": ticker,
                "price": float(row.get("最新价", 0)),
                "change": float(row.get("涨跌幅", 0)),
                "change_pct": float(row.get("振幅", 0)),
                "volume": int(row.get("成交量", 0)),
                "amount": float(row.get("成交额", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "open": float(row.get("今开", 0)),
                "prev_close": float(row.get("昨收", 0)),
            }

            return {"success": True, "data": quote_data, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_stock_history(self, params: dict) -> dict:
        """
        获取历史 K 线

        Args:
            params: {
                "ticker": "00700.HK",
                "interval": "1d" | "5d" | "1m",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "num": 100
            }

        Returns:
            dict: {"success": bool, "data": List[KLine], "message": str?}
        """
        ticker = params.get("ticker")
        interval = params.get("interval", "1d")
        num = params.get("num", 100)

        if not ticker:
            return {"success": False, "message": "Missing ticker parameter"}

        try:
            # 格式化 ticker
            if ticker.startswith("SH.") or ticker.startswith("SZ."):
                symbol = ticker.replace(".", "")
                df = ak.stock_zh_a_hist(
                    symbol=symbol, period="daily", start_date=params.get("start_date"), end_date=params.get("end_date")
                )
            elif "." in ticker:
                code = ticker.split(".")[0]
                market = "hk"
                df = ak.stock_hk_hist(
                    symbol=code, period="daily", start_date=params.get("start_date"), end_date=params.get("end_date")
                )
            else:
                return {"success": False, "message": "Unsupported ticker format"}

            if df.empty:
                return {"success": True, "data": [], "cached": False}

            klines = []
            for _, row in df.tail(num).iterrows():
                kline = {
                    "datetime": row.get("日期", ""),
                    "open": float(row.get("开盘", 0)),
                    "high": float(row.get("高", 0)),
                    "low": float(row.get("低", 0)),
                    "close": float(row.get("收盘", 0)),
                    "volume": int(row.get("成交量", 0)),
                }
                klines.append(kline)

            return {"success": True, "data": klines, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_hsgt_holders(self, params: dict) -> dict:
        """
        获取沪深港通/南向资金持股

        Args:
            params: {"symbol": "north_bound"} 或 {"symbol": "south_bound"}

        Returns:
            dict: {"success": bool, "data": List[HolderData], "message": str?}
        """
        symbol_type = params.get("symbol")

        try:
            if symbol_type == "north_bound":
                df = ak.stock_nh_top_holder_em()
            elif symbol_type == "south_bound":
                df = ak.stock_hsgt_north_holder_em()
            else:
                return {"success": False, "message": "Invalid symbol type"}

            holders = []
            for _, row in df.head(20).iterrows():
                holders.append(
                    {
                        "stock_code": row.get("股票代码", ""),
                        "stock_name": row.get("股票简称", ""),
                        "holding_qty": int(row.get("持有数量", 0)),
                        "holding_ratio": float(row.get("占流通股比例", 0)),
                        "change_qty": int(row.get("较上期变化数量", 0)),
                    }
                )

            return {"success": True, "data": holders, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _fetch_hsgt_top10(self, params: dict) -> dict:
        """
        获取北向资金前十名持仓

        Returns:
            dict: {"success": bool, "data": List[Top10Holding], "message": str?}
        """
        try:
            df = ak.stock_hsgt_top10_em()

            top10 = []
            for _, row in df.head(10).iterrows():
                top10.append(
                    {
                        "rank": int(row.get("排名", 0)),
                        "stock_code": row.get("股票代码", ""),
                        "stock_name": row.get("股票简称", ""),
                        "holding_ratio": float(row.get("占市值比例", 0)),
                        "change_ratio": float(row.get("较昨日变化", 0)),
                    }
                )

            return {"success": True, "data": top10, "cached": False}

        except Exception as e:
            return {"success": False, "message": str(e)}

    # ========== 辅助方法 ==========

    def health_check(self) -> dict:
        """健康检查"""
        try:
            df = ak.stock_zh_a_spot_em()
            return {
                "healthy": not df.empty,
                "message": "OK" if not df.empty else "No data",
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }
