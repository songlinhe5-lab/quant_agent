"""
AKShareService — AKShare 数据源实现（物理解耦裁剪版）

复制自 backend.services.akshare.service，按子服务职责裁剪：
- 移除 backend.core.retry_utils 依赖（改为 _internal.retry_utils）
- 移除 backend.services.finnhub.service 港股新闻兜底（子服务不再跨源兜底，
  get_hk_news 直接走 akshare，缺失部分由主服务经 router 另行补充）
- 移除 backend.core.redis_client / circuit_breaker 的 backend 前缀（改 _internal 相对 import）
"""

from typing import Any, Dict, List, Optional

from data_subservice._internal.akshare.calendar import get_economic_calendar
from data_subservice._internal.akshare.flow import (
    get_a_share_margin,
    get_a_share_sector_flow,
    get_hk_connect_flow,
    get_hk_sector_flow,
    get_hsgt_top_holders,
    get_individual_flow,
    get_lhb_detail,
    get_lhb_institution,
    get_lhb_stock_statistic,
    get_northbound_flow_full,
    get_southbound_flow,
)
from data_subservice._internal.akshare.quote import (
    get_company_news,
    get_history,
    get_hk_news,
    get_hk_stock_quote,
    get_spot_a_quote,
    get_stock_history_a_sina,
    get_stock_quote_a_sina,
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
            return get_northbound_flow_full()

        try:
            result = await circuit_breaker.call("akshare:flow", _call)
            self._record_success("flow")
            return result or {"error": "no flow data", "source": "akshare"}
        except Exception as e:
            self._record_failure("flow")
            return {"error": str(e), "source": "akshare"}

    async def get_southbound(self) -> Dict[str, Any]:
        def _call():
            return get_southbound_flow()

        try:
            result = await circuit_breaker.call("akshare:southbound", _call)
            self._record_success("southbound")
            return result or {"status": "warning", "data": None, "source": "akshare-unavailable"}
        except Exception as e:
            self._record_failure("southbound")
            return {"status": "error", "message": str(e), "data": None}

    async def get_hk_connect(self) -> Dict[str, Any]:
        def _call():
            return get_hk_connect_flow()

        try:
            result = await circuit_breaker.call("akshare:hk_connect", _call)
            self._record_success("hk_connect")
            return result or {"status": "warning", "data": None, "source": "akshare-unavailable"}
        except Exception as e:
            self._record_failure("hk_connect")
            return {"status": "error", "message": str(e), "data": None}

    async def get_hsgt_top_holders(self, symbol: str = "00700") -> Dict[str, Any]:
        def _call():
            return get_hsgt_top_holders(symbol)

        try:
            result = await circuit_breaker.call(f"akshare:holders:{symbol}", _call)
            self._record_success(f"holders:{symbol}")
            return result or {"status": "warning", "data": None, "source": "akshare-unavailable"}
        except Exception as e:
            self._record_failure(f"holders:{symbol}")
            return {"status": "error", "message": str(e), "data": None}

    async def get_stock_news(self, ticker: str) -> Dict[str, Any]:
        def _call():
            return get_company_news(ticker)

        try:
            result = await circuit_breaker.call(f"akshare:news:{ticker}", _call)
            self._record_success(f"news:{ticker}")
            return result or {"status": "success", "data": [], "source": "akshare"}
        except Exception as e:
            self._record_failure(f"news:{ticker}")
            return {"status": "error", "message": str(e), "data": []}

    async def get_quote_a(self, ticker: str) -> Dict[str, Any]:
        def _call():
            return get_stock_quote_a_sina(ticker)

        try:
            result = await circuit_breaker.call(f"akshare:quote:{ticker}", _call)
            self._record_success(f"quote:{ticker}")
            return result or {"status": "error", "message": "no data", "data": None}
        except Exception as e:
            self._record_failure(f"quote:{ticker}")
            return {"status": "error", "message": str(e), "data": None}

    async def get_history_a(self, ticker: str, num: int = 60) -> Dict[str, Any]:
        def _call():
            return get_stock_history_a_sina(ticker, num=num)

        try:
            result = await circuit_breaker.call(f"akshare:history:{ticker}", _call)
            self._record_success(f"history:{ticker}")
            return result or {"status": "error", "message": "no data", "data": None}
        except Exception as e:
            self._record_failure(f"history:{ticker}")
            return {"status": "error", "message": str(e), "data": None}

    async def get_econ_cal(self, days_ahead: int = 7, days_back: int = 0) -> Dict[str, Any]:
        def _call():
            return get_economic_calendar(days_ahead=days_ahead, days_back=days_back)

        try:
            result = await circuit_breaker.call("akshare:cal", _call)
            self._record_success("cal")
            return result or {"status": "error", "message": "no data", "data": []}
        except Exception as e:
            logger.warning(f"[AKShare] 宏观日历获取失败: {e}")
            self._record_failure("cal")
            return {"status": "error", "message": str(e), "data": []}

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

    async def get_margin_a_share(self) -> Dict[str, Any]:
        def _call():
            return get_a_share_margin()

        try:
            result = await circuit_breaker.call("akshare:margin", _call)
            self._record_success("margin")
            return result
        except Exception as e:
            self._record_failure("margin")
            return {"status": "error", "message": str(e), "data": None}

    async def get_sector_flow_a(self) -> Dict[str, Any]:
        def _call():
            return get_a_share_sector_flow()

        try:
            result = await circuit_breaker.call("akshare:sector_a", _call)
            self._record_success("sector_a")
            return result
        except Exception as e:
            self._record_failure("sector_a")
            return {"status": "error", "message": str(e), "data": None}

    async def get_sector_flow_hk(self) -> Dict[str, Any]:
        def _call():
            return get_hk_sector_flow()

        try:
            result = await circuit_breaker.call("akshare:sector_hk", _call)
            self._record_success("sector_hk")
            return result
        except Exception as e:
            self._record_failure("sector_hk")
            return {"status": "error", "message": str(e), "data": None}

    # ───────── FUNDFLOW-02: A股龙虎榜 ─────────
    async def get_lhb_detail(self, date: str) -> Dict[str, Any]:
        def _call():
            return get_lhb_detail(date)

        try:
            result = await circuit_breaker.call(f"akshare:lhb_detail:{date}", _call)
            self._record_success("lhb_detail")
            return result
        except Exception as e:
            self._record_failure("lhb_detail")
            return {"status": "error", "message": str(e), "data": None}

    async def get_lhb_stock_statistic(self, period: str = "近一月") -> Dict[str, Any]:
        def _call():
            return get_lhb_stock_statistic(period)

        try:
            result = await circuit_breaker.call(f"akshare:lhb_stat:{period}", _call)
            self._record_success("lhb_stat")
            return result
        except Exception as e:
            self._record_failure("lhb_stat")
            return {"status": "error", "message": str(e), "data": None}

    async def get_lhb_institution(self, start_date: str, end_date: str) -> Dict[str, Any]:
        def _call():
            return get_lhb_institution(start_date, end_date)

        try:
            result = await circuit_breaker.call(f"akshare:lhb_inst:{start_date}", _call)
            self._record_success("lhb_inst")
            return result
        except Exception as e:
            self._record_failure("lhb_inst")
            return {"status": "error", "message": str(e), "data": None}


# 全局单例
akshare_service = AKShareService()
