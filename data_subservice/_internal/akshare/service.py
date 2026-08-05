"""
AKShareService — AKShare 数据源实现（物理解耦裁剪版）

复制自 backend.services.akshare.service，按子服务职责裁剪：
- 移除 backend.core.retry_utils 依赖（改为 _internal.retry_utils）
- 移除 backend.services.finnhub.service 港股新闻兜底（子服务不再跨源兜底，
  get_hk_news 直接走 akshare，缺失部分由主服务经 router 另行补充）
- 移除 backend.core.redis_client / circuit_breaker 的 backend 前缀（改 _internal 相对 import）
"""

from typing import Any, Dict, List, Optional

from data_subservice._internal.akshare.calendar import (
    get_economic_calendar,
)
from data_subservice._internal.akshare.flow import get_individual_flow, get_northbound_flow
from data_subservice._internal.akshare.quote import (
    get_history,
    get_hk_news,
    get_hk_stock_quote,
    get_spot_a_quote,
    get_us_stock_quote,
)
from data_subservice._internal.circuit_breaker import circuit_breaker
from data_subservice._internal.logger import logger


class AKShareService:
    """AKShare 统一数据源（A股/港股/美股/宏观）。"""

    def __init__(self):
        self.source_name = "akshare"
        logger.info("✅ AKShareService (subservice) 初始化完成")

    def _record_success(self, symbol: str):
        circuit_breaker.record_success(symbol)

    def _record_failure(self, symbol: str, is_rate_limit: bool = False):
        circuit_breaker.record_failure(symbol, is_rate_limit=is_rate_limit)

    async def fetch_ak_data(
        self,
        endpoint: str,
        symbol: str = None,
        **kwargs,
    ) -> Any:
        endpoint = endpoint.lower()
        if endpoint == "quote":
            return await self.get_quote(symbol, **kwargs)
        elif endpoint == "history":
            return await self.get_history(symbol, **kwargs)
        elif endpoint == "flow":
            return await self.get_fund_flow(symbol, **kwargs)
        elif endpoint == "cal":
            return await self.get_econ_cal(**kwargs)
        elif endpoint == "news":
            return await self.get_hk_news(**kwargs)
        else:
            logger.warning(f"[AKShare] 未知 endpoint: {endpoint}")
            return {"symbol": symbol, "error": f"unknown endpoint: {endpoint}"}

    async def get_quote(self, symbol: str, market: str = "A") -> Dict[str, Any]:
        def _call():
            if market == "A":
                return get_spot_a_quote(symbol)
            elif market == "HK":
                return get_hk_stock_quote(symbol)
            elif market == "US":
                return get_us_stock_quote(symbol)
            return None

        try:
            result = await circuit_breaker.call(f"akshare:{symbol}", _call)
            self._record_success(symbol)
            return result or {"symbol": symbol, "error": "no data", "source": "akshare"}
        except Exception as e:
            self._record_failure(symbol, is_rate_limit="rate" in str(e).lower())
            return {"symbol": symbol, "error": str(e), "source": "akshare"}

    async def get_history(self, symbol: str, market: str = "A", period: str = "daily") -> Dict[str, Any]:
        def _call():
            df = get_history(symbol, market=market, period=period)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"akshare:{symbol}", _call)
            self._record_success(symbol)
            return {"symbol": symbol, "market": market, "data": records, "source": "akshare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "akshare"}

    async def get_fund_flow(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        def _call():
            if symbol:
                return get_individual_flow(symbol)
            return get_northbound_flow()

        try:
            result = await circuit_breaker.call("akshare:flow", _call)
            self._record_success("flow")
            return result or {"error": "no flow data", "source": "akshare"}
        except Exception as e:
            self._record_failure("flow")
            return {"error": str(e), "source": "akshare"}

    async def get_econ_cal(self) -> List[Dict[str, Any]]:
        def _call():
            return get_economic_calendar()

        try:
            result = await circuit_breaker.call("akshare:cal", _call)
            self._record_success("cal")
            return result
        except Exception as e:
            logger.warning(f"[AKShare] 宏观日历获取失败: {e}")
            self._record_failure("cal")
            return []

    async def get_hk_news(self, days: int = 3) -> List[Dict[str, Any]]:
        def _call():
            return get_hk_news(days=days)

        try:
            result = await circuit_breaker.call("akshare:news", _call)
            self._record_success("news")
            return result
        except Exception as e:
            logger.warning(f"[AKShare] 港股新闻获取失败: {e}")
            self._record_failure("news")
            return []


# 全局单例
akshare_service = AKShareService()
