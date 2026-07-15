"""
Legacy Market Data Gateway（BE-ARCH-01 / BE-ARCH-04）

唯一允许编排层引用具体数据源服务（futu / yf / akshare / finnhub / fred）的适配器。
Router 必须经 `backend.app.market_data.market_data` 访问，禁止直连。

YFinance 主路径经 DataSourceInterface Registry（`datasource_registry.fetch`）；
其它源仍为 Legacy 直调，后续按源逐步迁入 Interface。
"""

from __future__ import annotations

from typing import Any, Optional

from backend.core.ticker_format import format_yf_ticker


class MarketDataGateway:
    """实现 QuotePort 表面 + 选股/宏观等扩展方法。"""

    def __init__(self) -> None:
        from backend.services.akshare_service import akshare_service
        from backend.services.finnhub_service import finnhub_service
        from backend.services.fred_service import fred_service
        from backend.services.futu_service import futu_service
        from backend.services.yfinance_service import yf_service

        self._futu = futu_service
        self._yf = yf_service
        self._ak = akshare_service
        self._fh = finnhub_service
        self._fred = fred_service

        from backend.services.datasource.adapters.legacy_yfinance import (
            ensure_yfinance_registered,
        )

        ensure_yfinance_registered(self._yf)

    # ── QuotePort ──────────────────────────────────────────

    async def get_quote(self, ticker: str, **kwargs: Any) -> dict[str, Any]:
        return await self._futu.get_quote(ticker=ticker, **kwargs)

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 100, **kwargs: Any) -> dict[str, Any]:
        return await self._futu.get_history(ticker=ticker, ktype=ktype, num=num, **kwargs)

    async def get_fund_flow(self, ticker: str) -> dict[str, Any]:
        return await self._futu.get_fund_flow(ticker)

    async def get_option_chain(self, ticker: str, expiration_date: str = "") -> dict[str, Any]:
        res = await self._futu.get_option_chain(ticker, expiration_date)
        if res.get("status") == "error":
            msg = res.get("message", "")
            if "原生不支持" not in msg:
                pass  # 继续尝试 YF 降级
            yf_fallback = await self._option_chain_yfinance(ticker, expiration_date)
            if yf_fallback is not None:
                return yf_fallback
        return res

    async def _option_chain_yfinance(self, ticker: str, expiration_date: str) -> Optional[dict[str, Any]]:
        import asyncio

        import yfinance as yf

        yf_ticker = format_yf_ticker(ticker)

        def fetch_yf_options() -> dict[str, Any]:
            tk = yf.Ticker(yf_ticker)
            dates = tk.options
            if not dates:
                return {
                    "status": "error",
                    "message": f"{yf_ticker} 没有可用的期权链数据",
                }
            target_date = expiration_date if expiration_date in dates else dates[0]
            chain = tk.option_chain(target_date)
            compressed = []
            for _, row in chain.calls.head(30).iterrows():
                compressed.append(
                    {
                        "option_code": str(row.get("contractSymbol", "")),
                        "option_type": "CALL",
                        "strike_price": float(row.get("strike", 0.0)),
                        "last_price": float(row.get("lastPrice", 0.0) or 0.0),
                        "implied_volatility": float(row.get("impliedVolatility", 0.0) or 0.0),
                    }
                )
            for _, row in chain.puts.head(30).iterrows():
                compressed.append(
                    {
                        "option_code": str(row.get("contractSymbol", "")),
                        "option_type": "PUT",
                        "strike_price": float(row.get("strike", 0.0)),
                        "last_price": float(row.get("lastPrice", 0.0) or 0.0),
                        "implied_volatility": float(row.get("impliedVolatility", 0.0) or 0.0),
                    }
                )
            return {
                "status": "success",
                "data": {
                    "ticker": yf_ticker,
                    "expiration_date": target_date,
                    "options": compressed,
                    "source": "yfinance",
                },
            }

        try:
            return await asyncio.to_thread(fetch_yf_options)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Futu 扩展 ──────────────────────────────────────────

    async def get_fundamental(self, ticker: str) -> dict[str, Any]:
        return await self._futu.get_fundamental(ticker)

    def screen_stocks(self, market: str, filters: Any) -> Any:
        return self._futu.screen_stocks(market=market, filters=filters)

    @property
    def status(self) -> str:
        return self._futu.status

    @status.setter
    def status(self, value: str) -> None:
        self._futu.status = value

    @property
    def error_msg(self) -> str:
        return getattr(self._futu, "error_msg", "") or ""

    @error_msg.setter
    def error_msg(self, value: str) -> None:
        self._futu.error_msg = value

    @property
    def quote_ctx(self) -> Any:
        return getattr(self._futu, "quote_ctx", None)

    @quote_ctx.setter
    def quote_ctx(self, value: Any) -> None:
        self._futu.quote_ctx = value

    @property
    def conn_mgr(self) -> Any:
        return self._futu.conn_mgr

    @property
    def source_router(self) -> Any:
        return self._futu.source_router

    def connect(self) -> Any:
        return self._futu.connect()

    def is_opend_reachable(self, timeout: float = 2.0) -> bool:
        return bool(self._futu.conn_mgr._is_opend_reachable(timeout=timeout))

    def switch_opend_host(self, host: str, port: int = 11111) -> dict[str, Any]:
        result = self._futu.conn_mgr.switch_host(host, port)
        self._futu.status = self._futu.conn_mgr.status
        self._futu.error_msg = self._futu.conn_mgr.error_msg
        self._futu.quote_ctx = self._futu.conn_mgr.quote_ctx
        return result

    def futu_health_status(self) -> dict[str, Any]:
        return {
            "status": self._futu.status,
            "error": self._futu.error_msg,
            "reachable": self.is_opend_reachable(),
        }

    # ── YFinance ───────────────────────────────────────────

    async def get_tech_indicators(self, ticker: str, **kwargs: Any) -> Any:
        return await self._yf.get_tech_indicators(ticker=ticker, **kwargs)

    async def fetch_yf_data(self, ticker: str, req_type: str, **kwargs: Any) -> Any:
        """YFinance 主路径：DataSourceRegistry.fetch → Interface。"""
        from backend.services.datasource import ResultStatus, datasource_registry

        result = await datasource_registry.fetch(
            "yfinance",
            req_type if req_type in ("history", "info", "quote") else "fetch",
            {"ticker": ticker, "fetch_type": req_type, **kwargs},
        )
        if result.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            return True, result.data, ""
        msg = result.error.message if result.error else "yfinance fetch failed"
        return False, None, msg

    async def get_batched_quote(self, ticker: str, **kwargs: Any) -> Any:
        return await self._yf.get_batched_quote(ticker, **kwargs)

    def yf_health_status(self) -> dict[str, Any]:
        return self._yf.get_health_status()

    # ── AKShare / Finnhub / FRED ────────────────────────────

    def ak_health_status(self) -> dict[str, Any]:
        return self._ak.get_health_status()

    async def get_economic_calendar_ak(self, *args: Any, **kwargs: Any) -> Any:
        return await self._ak.get_economic_calendar(*args, **kwargs)

    async def get_southbound_flow(self) -> Any:
        return await self._ak.get_southbound_flow()

    async def get_northbound_flow(self) -> Any:
        return await self._ak.get_northbound_flow()

    async def get_hsgt_top_holders(self, symbol: str = "00700", **kwargs: Any) -> Any:
        return await self._ak.get_hsgt_top_holders(symbol=symbol, **kwargs)

    async def get_company_news_ak(self, ticker: str = "", **kwargs: Any) -> Any:
        return await self._ak.get_company_news(ticker=ticker, **kwargs)

    async def get_stock_quote_ak(self, ticker: str = "", **kwargs: Any) -> Any:
        return await self._ak.get_stock_quote(ticker=ticker, **kwargs)

    async def get_stock_history_ak(self, ticker: str, num: int = 60) -> Any:
        return await self._ak.get_stock_history(ticker, num=num)

    async def get_company_news_fh(
        self, ticker: str, days_back: int = 3, skip_cache: bool = False, **kwargs: Any
    ) -> Any:
        return await self._fh.get_company_news(ticker, days_back=days_back, skip_cache=skip_cache, **kwargs)

    async def get_earnings_calendar(
        self,
        days_ahead: int = 7,
        days_back: int = 0,
        skip_cache: bool = False,
        **kwargs: Any,
    ) -> Any:
        return await self._fh.get_earnings_calendar(
            days_ahead=days_ahead,
            days_back=days_back,
            skip_cache=skip_cache,
            **kwargs,
        )

    async def get_insider_transactions(self, ticker: str, limit: int = 30, **kwargs: Any) -> Any:
        return await self._fh.get_insider_transactions(ticker, limit=limit, **kwargs)

    async def get_market_news(self, category: str = "general", **kwargs: Any) -> Any:
        return await self._fh.get_market_news(category=category, **kwargs)

    async def get_stock_history_fh(self, ticker: str, days_back: int = 365, **kwargs: Any) -> Any:
        return await self._fh.get_stock_history(ticker, days_back=days_back, **kwargs)

    async def get_series_observations(self, series_id: str, limit: int = 5) -> Any:
        return await self._fred.get_series_observations(series_id, limit)

    async def get_economic_calendar_fred(self, *args: Any, **kwargs: Any) -> Any:
        return await self._fred.get_economic_calendar(*args, **kwargs)

    async def proxy_yfinance(self, ticker: str, fetch_type: str, kwargs: Optional[dict] = None) -> Any:
        kwargs = kwargs or {}
        if fetch_type == "quote":
            return await self.get_batched_quote(ticker, req_type="quote")
        if fetch_type == "tech":
            return await self.get_tech_indicators(ticker, **kwargs)
        if fetch_type == "history":
            success, data, msg = await self.fetch_yf_data(ticker, "history", ttl=3600, **kwargs)
            return {"success": success, "data": data, "message": msg}
        return {"success": False, "message": f"Unknown fetch_type: {fetch_type}"}

    async def proxy_akshare(self, action: str, kwargs: Optional[dict] = None) -> Any:
        kwargs = kwargs or {}
        mapping = {
            "southbound": self.get_southbound_flow,
            "northbound": self.get_northbound_flow,
            "hsgt_holders": lambda: self.get_hsgt_top_holders(symbol=kwargs.get("symbol", "00700")),
            "company_news": lambda: self.get_company_news_ak(ticker=kwargs.get("ticker", "")),
            "stock_quote": lambda: self.get_stock_quote_ak(ticker=kwargs.get("ticker", "")),
            "stock_history": lambda: self.get_stock_history_ak(
                ticker=kwargs.get("ticker", ""), num=kwargs.get("num", 60)
            ),
            "economic_calendar": lambda: self.get_economic_calendar_ak(days_ahead=kwargs.get("days_ahead", 7)),
        }
        fn = mapping.get(action)
        if not fn:
            return {"status": "error", "message": f"Unknown akshare action: {action}"}
        return await fn()


# Composition root 单例
market_data_gateway = MarketDataGateway()
