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
