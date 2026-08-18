"""
Legacy Market Data Gateway（BE-ARCH-01 / BE-ARCH-04）

唯一允许编排层引用具体数据源服务（futu / yf / akshare / finnhub / fred）的适配器。
Router 必须经 `backend.app.market_data.market_data` 访问，禁止直连。

YFinance 主路径经 DataSourceInterface Registry（`datasource_registry.fetch`）；
其它源仍为 Legacy 直调，后续按源逐步迁入 Interface。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.core.ticker_format import format_yf_ticker
from backend.domain.options_engine import compute_option_chain_greeks

logger = logging.getLogger(__name__)


class MarketDataGateway:
    """实现 QuotePort 表面 + 选股/宏观等扩展方法。"""

    def __init__(self) -> None:
        from backend.services.akshare import akshare_service

        # futu_service 延迟到首次使用时导入，避免主节点无 SDK 时启动崩溃
        self._futu = None
        self._ak = akshare_service
        # dbnomics/fred/rbi 经 services.macro 间接依赖 hermes_agent；若在 __init__
        # 同步 import，模块级 `market_data_gateway = MarketDataGateway()` 会触发
        # 循环导入 (legacy_market_data -> macro -> ai_narrator -> hermes -> legacy_market_data)。
        # 改为 lazy property，首次使用时（模块已全部加载）再导入。
        self._fred = None
        self._dbnomics = None
        self._rbi = None

    @property
    def futu(self):
        """延迟导入 futu_service。"""
        if self._futu is None:
            from backend.services.futu import futu_service

            self._futu = futu_service
        return self._futu

    @property
    def dbnomics(self):
        """延迟导入 dbnomics_service，避免模块加载期循环导入。"""
        if self._dbnomics is None:
            from backend.services.macro.dbnomics import dbnomics_service

            self._dbnomics = dbnomics_service
        return self._dbnomics

    @property
    def fred(self):
        """延迟导入 fred_service，避免模块加载期循环导入。"""
        if self._fred is None:
            from backend.services.macro.fred_service import fred_service

            self._fred = fred_service
        return self._fred

    @property
    def rbi(self):
        """延迟导入 rbi_service，避免模块加载期循环导入。"""
        if self._rbi is None:
            from backend.services.macro.rbi import rbi_service

            self._rbi = rbi_service
        return self._rbi

        from backend.services.datasource.adapters.legacy_yfinance import (
            ensure_yfinance_registered,
        )

        ensure_yfinance_registered()

        from backend.services.datasource.adapters.fmp import (
            ensure_fmp_registered,
        )

        ensure_fmp_registered()

    # ── QuotePort ──────────────────────────────────────────

    async def get_quote(self, ticker: str, **kwargs: Any) -> dict[str, Any]:
        # BE-ARCH-07a: Futu 直调改为经 DataSourceRegistry 远程路由（子服务化，移除主服务本地 SDK）
        from backend.services.datasource import ResultStatus, datasource_registry

        # 行情路由：Futu 优先（低延迟、港股原生覆盖好），失败降级 YFinance 兜底（YF 辅节点更"永远在线"）
        result = await datasource_registry.fetch("futu", "QUOTE", {"ticker": ticker, **kwargs})
        if result.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            data = result.data
            data["_fallback"] = data.get("_fallback") or "futu"
            return data
        yf_res = await datasource_registry.fetch("yfinance", "QUOTE", {"ticker": ticker, **kwargs})
        if yf_res.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            data = yf_res.data
            data["_fallback"] = "yfinance"
            data["_note"] = "Futu QUOTE 不可用，已降级至 YFinance"
            return data
        return {
            "status": "error",
            "message": yf_res.error.message if yf_res.error else "futu/yfinance QUOTE 路由均失败",
        }

    async def get_history(self, ticker: str, ktype: str = "K_DAY", num: int = 100, **kwargs: Any) -> dict[str, Any]:
        from backend.services.datasource import ResultStatus, datasource_registry

        # 行情路由：Futu 优先，失败降级 YFinance 兜底
        result = await datasource_registry.fetch(
            "futu", "HISTORY", {"ticker": ticker, "ktype": ktype, "num": num, **kwargs}
        )
        if result.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            data = result.data
            data["_fallback"] = data.get("_fallback") or "futu"
            return data
        yf_res = await datasource_registry.fetch(
            "yfinance", "HISTORY", {"ticker": ticker, "ktype": ktype, "num": num, **kwargs}
        )
        if yf_res.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            data = yf_res.data
            data["_fallback"] = "yfinance"
            data["_note"] = "Futu HISTORY 不可用，已降级至 YFinance"
            return data
        return {
            "status": "error",
            "message": yf_res.error.message if yf_res.error else "futu/yfinance HISTORY 路由均失败",
        }

    async def get_fund_flow(self, ticker: str) -> dict[str, Any]:
        from backend.services.datasource import ResultStatus, datasource_registry

        result = await datasource_registry.fetch("futu", "FUND_FLOW", {"ticker": ticker})
        if result.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            return result.data
        return {"status": "error", "message": result.error.message if result.error else "futu FUND_FLOW 路由失败"}

    async def get_warrant_chain(self, ticker: str) -> dict[str, Any]:
        """港股窝轮/牛熊证链（仅 HK 标的可用），经 DataSourceRegistry 远程路由。"""
        from backend.services.datasource import ResultStatus, datasource_registry

        result = await datasource_registry.fetch("futu", "WARRANT_CHAIN", {"ticker": ticker})
        if result.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            return result.data
        return {"status": "error", "message": result.error.message if result.error else "futu WARRANT_CHAIN 路由失败"}

    async def get_option_chain(self, ticker: str, expiration_date: str = "") -> dict[str, Any]:
        from backend.services.datasource import ResultStatus, datasource_registry

        futu_res = await datasource_registry.fetch(
            "futu", "OPTION_CHAIN", {"ticker": ticker, "expiration_date": expiration_date}
        )
        if futu_res.status in (ResultStatus.SUCCESS, ResultStatus.DEGRADED):
            res = futu_res.data
        else:
            res = {
                "status": "error",
                "message": futu_res.error.message if futu_res.error else "futu OPTION_CHAIN 路由失败",
            }
        # 💡 Futu 快照期权链常只含 option_code/strike_price 而无定价字段(bid/ask/IV)，
        # 此时虽 status=success 却无法用于 Greeks/IV 计算 → 降级到 YFinance 补全定价数据。
        if res.get("status") == "error" or self._option_chain_lacks_pricing(res):
            yf_fallback = await self._option_chain_yfinance(ticker, expiration_date)
            if yf_fallback is not None and yf_fallback.get("status") == "success":
                return yf_fallback
            # 💡 港股标的无挂牌个股期权时，降级到窝轮/牛熊证链（WRNT-04）
            if self._is_hk_ticker(ticker):
                warrant_res = await self.get_warrant_chain(ticker)
                if warrant_res.get("status") == "success":
                    warrant_res["_fallback"] = "warrant_chain"
                    warrant_res["_note"] = "该港股无挂牌个股期权，已降级为窝轮/牛熊证数据（市场多空情绪替代）"
                    return warrant_res
        # 补充 Greeks / IV（期权链含定价字段时），并按类型拆分 calls/puts
        spot = res.get("underlying_price")
        if spot is None:
            try:
                q = await self.get_quote(ticker)
                spot = (q or {}).get("last_price")
            except Exception:
                spot = None
        return self._enrich_option_chain(res, spot)

    def _enrich_option_chain(self, res: dict, spot: Optional[float], risk_free: float = 0.045) -> dict:
        """为期权链补齐 Greeks/IV（Black-Scholes），并按类型拆分 calls/puts。"""
        opts = res.get("options") or []
        if not opts:
            return res
        if spot is None:
            # 无法计算 Greeks，仅做类型拆分
            res["calls"] = [o for o in opts if str(o.get("option_type", "")).upper() == "CALL"]
            res["puts"] = [o for o in opts if str(o.get("option_type", "")).upper() == "PUT"]
            return res
        norm = []
        for o in opts:
            norm.append(
                {
                    "strike": o.get("strike_price") or o.get("strike") or 0,
                    "expiry": o.get("expiration_date") or res.get("expiration_date") or "",
                    "option_type": o.get("option_type") or "call",
                    "bid": o.get("bid") or 0,
                    "ask": o.get("ask") or 0,
                    "volume": o.get("volume") or 0,
                    "open_interest": o.get("open_interest") or 0,
                    "days_to_expiry": o.get("days_to_expiry") or 30,
                    "iv": o.get("implied_volatility"),
                }
            )
        try:
            enriched = compute_option_chain_greeks(spot, risk_free, norm)
        except Exception:
            enriched = norm
        for o, e in zip(opts, enriched):
            o["iv"] = e.get("iv")
            o["greeks"] = e.get("greeks")
            o["moneyness"] = e.get("moneyness")
            # 兼容既有 compute_option_chain_greeks(读取 opt.get("strike"))
            o["strike"] = o.get("strike_price")
            if o.get("days_to_expiry") is None:
                o["days_to_expiry"] = e.get("days_to_expiry")
        res["calls"] = [o for o in opts if str(o.get("option_type", "")).upper() == "CALL"]
        res["puts"] = [o for o in opts if str(o.get("option_type", "")).upper() == "PUT"]
        res["underlying_price"] = spot
        return res

    async def _get_option_expiration_dates(self, ticker: str) -> tuple[list[str], str]:
        """获取期权到期日列表。优先 Futu 真实源，不可用则 YFinance 降级。

        Returns:
            (到期日列表, 数据源标识) ; 均无数据时返回 ([], "none")
        """
        futu = getattr(self, "_futu", None)
        if futu is not None and getattr(futu, "connected", False):
            try:
                if hasattr(futu, "get_option_expiration_date_list"):
                    dates = await futu.get_option_expiration_date_list(ticker)
                    if dates:
                        return list(dates), "futu"
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[MarketData] Futu 取到期日失败, 降级 YF: {e}")
        # YFinance 降级（经子服务；后端不再本地跑 yfinance）
        try:
            from backend.services.datasource.router import data_source_router

            res = await data_source_router.fetch_yfinance(format_yf_ticker(ticker), "option_chain")
            if res.get("success") or res.get("status") == "success":
                data = res.get("data") or res
                opts = list((data.get("expiration_dates") or data.get("options") or []) or [])
                if isinstance(opts, list) and opts and isinstance(opts[0], str):
                    return opts, "yfinance-subservice"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MarketData] YF 子服务取到期日失败: {e}")
        return [], "none"

    async def get_option_chain_matrix(
        self, ticker: str, max_expiries: int = 8, max_strikes: int = 21
    ) -> dict[str, Any]:
        """跨到期日的 IV 波动率曲面，供前端热力图使用。

        优先 Futu 真实源；Futu 未连接时自动降级到 YFinance 真实期权链
        (OPTION-01 修复: 旧逻辑强制 Futu 连接会令真实 YF 数据也取不到)。
        任何异常均显式返回错误，绝不用 Mock 填充 (VIBE-CODING)。
        """
        try:
            exp_dates, src = await self._get_option_expiration_dates(ticker)
            if not exp_dates:
                return {
                    "status": "error",
                    "message": (
                        f"数据源已死，无法分析：未获取到 {ticker} 的期权到期日列表 (Futu/YFinance 均无可用真实数据)"
                    ),
                }

            expirations: list = []
            iv_call, iv_put, delta_call, delta_put = [], [], [], []
            strikes_set: set = set()
            legs: list = []
            degraded_signal = False
            degraded_msgs: list[str] = []
            for exp in exp_dates[:max_expiries]:
                chain = await self.get_option_chain(ticker, exp)
                if chain.get("status") != "success":
                    logger.warning(f"[MarketData] matrix: 到期 {exp} 取链失败: {chain.get('message')}")
                    continue
                # 透传子服务降级信号：futu 快照补充 IV 失败且 YF 兜底也失败时，期权链可用但 IV 缺失
                if chain.get("degraded"):
                    degraded_signal = True
                    m = chain.get("degraded_message") or "期权链数据降级"
                    if m not in degraded_msgs:
                        degraded_msgs.append(m)
                opts = chain.get("options") or []
                if not opts:
                    continue
                expirations.append(exp)
                c_map, p_map = {}, {}
                for o in opts:
                    k = o.get("strike") or o.get("strike_price")
                    if k is None:
                        continue
                    g = o.get("greeks") or {}
                    entry = {"iv": o.get("iv"), "delta": g.get("delta")}
                    if str(o.get("option_type", "")).upper() == "CALL":
                        c_map[k] = entry
                    else:
                        p_map[k] = entry
                    strikes_set.add(k)
                strikes = sorted(strikes_set)
                iv_call.append([c_map.get(s, {}).get("iv") for s in strikes])
                iv_put.append([p_map.get(s, {}).get("iv") for s in strikes])
                delta_call.append([c_map.get(s, {}).get("delta") for s in strikes])
                delta_put.append([p_map.get(s, {}).get("delta") for s in strikes])
                for s in strikes:
                    if c_map.get(s):
                        legs.append({"type": "call", "expiry": exp, "strike": s, **c_map[s]})
                    if p_map.get(s):
                        legs.append({"type": "put", "expiry": exp, "strike": s, **p_map[s]})
            if not expirations:
                return {
                    "status": "error",
                    "message": f"未构建出 {ticker} 的有效期权曲面 (各到期日均无真实数据)",
                }
            spot = None
            try:
                q = await self.get_quote(ticker)
                spot = (q or {}).get("last_price")
            except Exception:
                spot = None
            resp = {
                "status": "success",
                "symbol": ticker,
                "underlying_price": spot,
                "expirations": expirations,
                "strikes": sorted(strikes_set),
                "calls": {"iv": iv_call, "delta": delta_call},
                "puts": {"iv": iv_put, "delta": delta_put},
                "legs": legs,
                "source": src,
            }
            if degraded_signal:
                resp["degraded"] = True
                resp["degraded_message"] = "IV/Greeks 快照补充失败（futu 快照 + YF 兜底均不可用），部分到期日 IV 缺失"
            return resp
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MarketDataGateway] 生产期权矩阵组装失败: {e}")
            return {
                "status": "error",
                "message": f"期权 IV 曲面组装失败（数据源异常）: {e}",
            }

    @staticmethod
    def _is_hk_ticker(ticker: str) -> bool:
        """判断是否为港股标的"""
        t = ticker.upper()
        return t.endswith(".HK") or (t.isdigit() and len(t) <= 5)

    @staticmethod
    def _option_chain_lacks_pricing(res: dict) -> bool:
        """判断 Futu 期权链是否缺少定价字段(无法计算 Greeks/IV 即视为残缺)

        ⚠️ Futu 期权链 options 在顶层(res.options)，YF 在 res.data.options，
        两种结构都要兼容。
        """
        opts = res.get("options") or (res.get("data") or {}).get("options") or []
        if not opts:
            return False
        pricing_keys = ("last_price", "bid", "ask", "implied_volatility")
        for o in opts[:5]:
            if any(k in o for k in pricing_keys):
                return False
        return True

    async def _option_chain_yfinance(self, ticker: str, expiration_date: str) -> Optional[dict[str, Any]]:
        """经 DataSourceRouter 向 US-YF-A/B 子服务拉期权链（后端不再本地跑 yfinance）。"""
        from backend.services.datasource.router import data_source_router

        yf_ticker = format_yf_ticker(ticker)
        try:
            result = await data_source_router.fetch_yfinance(
                yf_ticker,
                "option_chain",
                expiration=expiration_date if expiration_date else None,
            )
        except Exception as e:
            return {"status": "error", "message": f"YF 子服务期权链失败: {e}"}

        if not result.get("success") and result.get("status") != "success":
            return {
                "status": "error",
                "message": result.get("message", "YF 子服务未返回期权链"),
            }

        data = result.get("data") or result
        # 子服务返回可能为 {options:[...]} 或 {calls:[...], puts:[...]}；
        # 统一归一化为顶层 options 结构，兼容 consumer 期望。
        options = data.get("options")
        if options is None:
            calls = data.get("calls", []) or []
            puts = data.get("puts", []) or []
            options = [{**c, "option_type": "CALL"} for c in calls[:30]] + [
                {**p, "option_type": "PUT"} for p in puts[:30]
            ]
        # 按到期日过滤：主服务逐到期日调用，子服务返回全部到期日合并的合约，
        # 需按 expiration 字段筛选，否则矩阵每个到期日都会显示全部合约。
        if expiration_date:
            options = [o for o in options if str(o.get("expiration")) == str(expiration_date)]
        return {
            "status": "success",
            "options": options,
            "expiration_date": data.get("expiration_date", expiration_date),
            "source": "yfinance-subservice",
            "count": len(options),
            "ticker": yf_ticker,
            "message": "yfinance 期权链(含 IV/定价字段，经子服务)",
        }

    # ── Futu 扩展 ──────────────────────────────────────────

    async def get_fundamental(self, ticker: str) -> dict[str, Any]:
        return await self.futu.get_fundamental(ticker)

    def screen_stocks(self, market: str, filters: Any) -> Any:
        return self.futu.screen_stocks(market=market, filters=filters)

    @property
    def status(self) -> str:
        return self.futu.status

    @status.setter
    def status(self, value: str) -> None:
        self.futu.status = value

    @property
    def error_msg(self) -> str:
        return getattr(self.futu, "error_msg", "") or ""

    @error_msg.setter
    def error_msg(self, value: str) -> None:
        self.futu.error_msg = value

    @property
    def quote_ctx(self) -> Any:
        return getattr(self.futu, "quote_ctx", None)

    @quote_ctx.setter
    def quote_ctx(self, value: Any) -> None:
        self.futu.quote_ctx = value

    @property
    def conn_mgr(self) -> Any:
        return self.futu.conn_mgr

    @property
    def source_router(self) -> Any:
        return self.futu.source_router

    def connect(self) -> Any:
        return self.futu.connect()

    def is_opend_reachable(self, timeout: float = 2.0) -> bool:
        # BE-ARCH-09: 主服务远程-only, 无本地 OpenD, 主机可达性由子服务负责
        return bool(self.futu.is_opend_reachable(timeout=timeout))

    def switch_opend_host(self, host: str, port: int = 11111) -> dict[str, Any]:
        # BE-ARCH-09: 主服务远程-only, 不再切换本地 OpenD 连接; 兼容占位返回
        return self.futu.switch_opend_host(host, port)

    def futu_health_status(self) -> dict[str, Any]:
        return {
            "status": self.futu.status,
            "error": self.futu.error_msg,
            "reachable": self.is_opend_reachable(),
        }

    # ── YFinance（远程子服务，后端不再本地执行 yfinance）───────────

    async def get_tech_indicators(self, ticker: str, **kwargs: Any) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_yfinance(format_yf_ticker(ticker), "tech")

    async def fetch_yf_data(self, ticker: str, req_type: str, **kwargs: Any) -> Any:
        """YFinance 主路径：DataSourceRegistry.fetch → Interface（远程子服务）。"""
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
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_yfinance(format_yf_ticker(ticker), "quote")

    def yf_health_status(self) -> dict[str, Any]:
        from backend.services.datasource.registry import rate_limit_registry

        throttler = rate_limit_registry.get_throttler("yfinance")
        rl = throttler.get_status()
        return {
            "status": "remote",
            "mode": "subservice",
            "is_throttled": rl.is_throttled,
            "note": "yfinance 流量已全量外移至 US-YF-A/B 子服务",
        }

    # ── AKShare / Finnhub / FRED ────────────────────────────

    def ak_health_status(self) -> dict[str, Any]:
        return self._ak.get_health_status()

    async def get_economic_calendar_ak(self, *args: Any, **kwargs: Any) -> Any:
        """经济日历 - 纯远程 AKShare 子服务（无本地降级，源失效在监控如实显示）

        返回统一信封 {"status":"success","data":[...]}，与 fred/dbnomics/rbi 的
        get_economic_calendar 契约对齐。MacroCalendarAggregator._extract 期望 res 是
        带 data 键的 dict；此前这里直接返回 result.get("data")（裸 list），剥内层信封后
        会导致 _extract 的 isinstance(res, dict) 判定失败 → 经济日历被吞成空。
        """
        from backend.services.datasource.router import data_source_router

        result = await data_source_router.fetch_akshare("ECONOMIC_CALENDAR", **kwargs)
        if result.get("status") == "success":
            return {"status": "success", "data": result.get("data", []), "source": "akshare"}
        logger.warning(f"[AKShare] 经济日历远程调用失败：{result.get('message')}")
        return {"status": "error", "data": [], "source": "akshare", "message": result.get("message")}

    async def get_southbound_flow(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("SOUTHBOUND")

    async def get_northbound_flow(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("FUND_FLOW")

    async def get_hk_stock_connect_flow(self) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("HK_CONNECT")

    async def get_hsgt_top_holders(self, symbol: str = "00700", **kwargs: Any) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("HSGT_HOLDERS", symbol=symbol)

    async def get_company_news_ak(self, ticker: str = "", **kwargs: Any) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("STOCK_NEWS", ticker=ticker)

    async def get_stock_quote_ak(self, ticker: str = "", **kwargs: Any) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("QUOTE_A", ticker=ticker)

    async def get_stock_history_ak(self, ticker: str, num: int = 60) -> Any:
        from backend.services.datasource.router import data_source_router

        return await data_source_router.fetch_akshare("HISTORY_A", ticker=ticker, num=num)

    async def get_company_news_fh(
        self, ticker: str, days_back: int = 3, skip_cache: bool = False, **kwargs: Any
    ) -> Any:
        resp = await self._fetch_finnhub("company_news", ticker=ticker, days_back=days_back)
        return resp

    async def get_earnings_calendar(
        self,
        days_ahead: int = 7,
        days_back: int = 0,
        skip_cache: bool = False,
        **kwargs: Any,
    ) -> Any:
        resp = await self._fetch_finnhub(
            "earnings",
            days_ahead=days_ahead,
            days_back=days_back,
        )
        # _fetch_finnhub 成功时返回 router 剥信封后的 data 载荷，即 Finnhub 原始
        # {"earningsCalendar":[...]}；失败时返回 {"status":"error","message":...} 信封。
        # 归一化为业务层统一信封 {"status":"success","data":[...]}，否则上游
        # _fetch_earnings_calendar_data 拿不到 status/data 字段 → 财报日历被吞成空。
        if isinstance(resp, dict) and resp.get("status") == "error":
            return resp
        calendar = resp.get("earningsCalendar", []) if isinstance(resp, dict) else []
        return {"status": "success", "data": calendar, "source": "finnhub"}

    async def get_insider_transactions(self, ticker: str, limit: int = 30, **kwargs: Any) -> Any:
        resp = await self._fetch_finnhub("insider_trading", ticker=ticker, limit=limit)
        return resp

    async def get_market_news(self, category: str = "general", **kwargs: Any) -> Any:
        resp = await self._fetch_finnhub("market_news", category=category)
        return resp

    async def get_stock_history_fh(self, ticker: str, days_back: int = 365, **kwargs: Any) -> Any:
        resp = await self._fetch_finnhub("stock_history", ticker=ticker, days_back=days_back)
        return resp

    async def get_series_observations(self, series_id: str, limit: int = 5, force_refresh: bool = False) -> Any:
        return await self.fred.get_series_observations(series_id, limit, force_refresh=force_refresh)

    async def get_economic_calendar_fred(self, *args: Any, **kwargs: Any) -> Any:
        return await self.fred.get_economic_calendar(*args, **kwargs)

    async def get_economic_calendar_finnhub(self, *args: Any, **kwargs: Any) -> Any:
        resp = await self._fetch_finnhub("economic_calendar", *args, **kwargs)
        # _fetch_finnhub 成功返回 Finnhub 原始 {"economicCalendar":[...]}，归一化为
        # {"status":"success","data":[...]} 信封，与 fred/dbnomics/rbi 契约对齐
        # (MacroCalendarAggregator._extract 期望 res 带 data 键且为 list)。
        if isinstance(resp, dict) and resp.get("status") == "error":
            return resp
        calendar = resp.get("economicCalendar", []) if isinstance(resp, dict) else []
        return {"status": "success", "data": calendar, "source": "finnhub"}

    @staticmethod
    async def _fetch_finnhub(action: str, *args: Any, **kwargs: Any) -> Any:
        """经 DataSourceRouter 远程调用 finnhub 子服务，返回 data 载荷。"""
        from backend.services.datasource.router import data_source_router

        resp = await data_source_router.fetch_finnhub(action, *args, **kwargs)
        if isinstance(resp, dict) and resp.get("status") == "success":
            return resp.get("data")
        return resp

    async def get_economic_calendar_dbnomics(self, *args: Any, **kwargs: Any) -> Any:
        return await self.dbnomics.get_economic_calendar(*args, **kwargs)

    async def get_economic_calendar_rbi(self, *args: Any, **kwargs: Any) -> Any:
        return await self.rbi.get_economic_calendar(*args, **kwargs)

    async def backfill_fred_actuals(self, events: Any, *args: Any, **kwargs: Any) -> Any:
        return await self.fred.backfill_actuals(events, *args, **kwargs)


# Composition root 单例
market_data_gateway = MarketDataGateway()
