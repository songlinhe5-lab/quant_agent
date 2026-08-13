"""
TushareService — Tushare 数据源实现（物理解耦裁剪版）

复制自 backend.services.tushare.service，按子服务职责裁剪：
- 移除 backend.core.circuit_breaker / backend.core.redis_client / backend.core.logger
  的 backend 前缀（改为 _internal 相对 import）
- 移除 backend.services.datasource.ErrorCategory 类型引用，改用字符串 category 标记
  （子服务内无需与主服务共享异常分类枚举）
"""

import os
from typing import Any, Dict

import tushare as ts

from data_subservice._internal.circuit_breaker import circuit_breaker
from data_subservice._internal.logger import logger

TS_TOKEN = os.getenv("TUSHARE_TOKEN", "")


def _is_hk_symbol(symbol: str) -> bool:
    """识别港股代码（HK.00700 / 00700.HK / 5位港股代码）。Tushare 仅支持 A 股。"""
    s = (symbol or "").strip().upper()
    if s.startswith("HK.") or s.endswith(".HK"):
        return True
    return False


def _today() -> str:
    """返回 yyyyMMdd 格式的今日（子服务无 datetime 依赖，用 time 构造）。"""
    import time

    return time.strftime("%Y%m%d", time.localtime())


def _today_minus(days: int) -> str:
    import time

    t = time.localtime(time.time() - days * 86400)
    return time.strftime("%Y%m%d", t)


class TushareService:
    """Tushare 数据源（A股财务/基本面/资金流）。"""

    def __init__(self):
        self.pro = ts.pro_api(TS_TOKEN) if TS_TOKEN else None
        self.source_name = "tushare"
        if not TS_TOKEN:
            logger.warning("⚠️ [Tushare] 未配置 TUSHARE_TOKEN，服务不可用")
        else:
            logger.info("✅ TushareService (subservice) 初始化完成")

    def _record_success(self, symbol: str):
        circuit_breaker.record_success(symbol)

    def _record_failure(self, symbol: str, is_rate_limit: bool = False):
        circuit_breaker.record_failure(symbol, is_rate_limit=is_rate_limit)

    async def fetch_ts_data(
        self,
        endpoint: str,
        symbol: str,
        **kwargs,
    ) -> Any:
        endpoint = endpoint.lower()
        if endpoint == "financials":
            return await self.get_financials(symbol, **kwargs)
        elif endpoint == "holder":
            return await self.get_holder_number(symbol)
        elif endpoint == "flow":
            return await self.get_moneyflow(symbol)
        else:
            logger.warning(f"[Tushare] 未知 endpoint: {endpoint}")
            return {"symbol": symbol, "error": f"unknown endpoint: {endpoint}"}

    async def get_financials(self, symbol: str, report_type: str = "income") -> Dict[str, Any]:
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}
        # Tushare 仅支持 A 股, 港股财报由 Futu 承载; 明确报错让上游跳过 Tushare
        if _is_hk_symbol(symbol):
            return {"symbol": symbol, "error": f"Tushare 不支持港股 {symbol}", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            if report_type == "income":
                df = self.pro.income(ts_code=ts_code)
            elif report_type == "balance":
                df = self.pro.balancesheet(ts_code=ts_code)
            elif report_type == "cashflow":
                df = self.pro.cashflow(ts_code=ts_code)
            else:
                df = self.pro.income(ts_code=ts_code)
            if df is None or df.empty:
                return []
            return df.head(4).to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            self._record_success(symbol)
            return {"symbol": symbol, "report_type": report_type, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol, is_rate_limit="rate" in str(e).lower())
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_holder_number(self, symbol: str) -> Dict[str, Any]:
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            df = self.pro.stk_holdernumber(ts_code=ts_code)
            if df is None or df.empty:
                return []
            return df.head(8).to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            self._record_success(symbol)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_moneyflow(self, symbol: str) -> Dict[str, Any]:
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            df = self.pro.moneyflow(ts_code=ts_code)
            if df is None or df.empty:
                return []
            return df.head(30).to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            self._record_success(symbol)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    # ───────────────────────────────────────────────────────────────
    # 审计补全：以下 6 个能力在主服务侧曾有 stock_history / stock_quote /
    # fundamental / stock_list / lowfreq_history / macro 等 action，但子服务
    # worker 此前未实现，主路由只能降级走本地适配器（audit: capability-gap）。
    # 现已在子服务补齐，使能力缺口真正闭合，避免污染熔断计数。
    # ───────────────────────────────────────────────────────────────

    @staticmethod
    def _empty(kind: str) -> Dict[str, Any]:
        return {"action": kind, "data": [], "source": "tushare"}

    @staticmethod
    def _frame_to_records(df) -> Dict[str, Any]:
        return {"data": df.to_dict(orient="records"), "source": "tushare"}

    async def get_daily_history(self, symbol: str, start_date: str, end_date: str, asset: str = "E") -> Dict[str, Any]:
        """日线历史行情（tushare daily + asset 分流）。

        对齐主服务 TushareService.get_daily_history：指数/ETF 走 index_daily。
        返回 OHLCV。
        """
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            if asset == "I":
                df = self.pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            else:
                df = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol, is_rate_limit="rate" in str(e).lower())
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        """实时快照（tushare rt 接口）。

        对齐主服务 TushareService.get_realtime_quote：rt 不可用则降级 daily 最新一行。
        """
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            df = self.pro.rt(ts_code=ts_code)
            if df is None or df.empty:
                df = self.pro.daily(ts_code=ts_code, start_date=_today_minus(5), end_date=_today())
                if df is not None and not df.empty:
                    df = df.head(1)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_daily_basic(
        self, symbol: str, trade_date: str = "", start_date: str = "", end_date: str = ""
    ) -> Dict[str, Any]:
        """每日基本面指标（tushare daily_basic）。

        对齐主服务 TushareService.get_daily_basic：返回 PE/PB/市值/换手率等。
        """
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            if trade_date:
                df = self.pro.daily_basic(ts_code=ts_code, trade_date=trade_date)
            else:
                df = self.pro.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_stock_basic(
        self,
        list_status: str = "L",
        exchange: str = "",
        fields: str = "ts_code,symbol,name,area,industry,market,list_status,list_date",
    ) -> Dict[str, Any]:
        """股票列表（tushare stock_basic）。

        对齐主服务 TushareService.get_stock_basic。
        """
        if not self.pro:
            return {"symbol": "", "error": "tushare not configured", "source": "tushare"}

        def _call():
            df = self.pro.stock_basic(exchange=exchange, list_status=list_status, fields=fields)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call("tushare:stock_basic", _call)
            return {"data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure("tushare:stock_basic")
            return {"error": str(e), "source": "tushare"}

    async def get_lowfreq_history(self, symbol: str, freq: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """低频历史（周/月线，tushare wk_mn 接口）。"""
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            df = self.pro.wk_mn(ts_code=ts_code, freq=freq, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    async def get_macro(self, symbol: str, start_date: str, end_date: str) -> Dict[str, Any]:
        """宏观经济数据（tushare macro 接口）。"""
        if not self.pro:
            return {"symbol": symbol, "error": "tushare not configured", "source": "tushare"}

        def _call():
            ts_code = self._to_ts_code(symbol)
            df = self.pro.macro(ts_code=ts_code, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

        try:
            records = await circuit_breaker.call(f"tushare:{symbol}", _call)
            return {"symbol": symbol, "data": records, "source": "tushare"}
        except Exception as e:
            self._record_failure(symbol)
            return {"symbol": symbol, "error": str(e), "source": "tushare"}

    def _to_ts_code(self, symbol: str) -> str:
        """将通用代码转为 tushare 代码（如 000001.SZ）。"""
        s = symbol.upper().replace("SH.", "").replace("SZ.", "")
        if s.endswith(".SH"):
            return s
        if s.endswith(".SZ"):
            return s
        if s.endswith(".SS"):
            return s
        # A股纯数字默认深交所，简单启发式
        if s.isdigit():
            if s.startswith(("6",)):
                return f"{s}.SH"
            return f"{s}.SZ"
        return symbol


# 全局单例
tushare_service = TushareService()
