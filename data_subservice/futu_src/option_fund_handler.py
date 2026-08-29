"""
Futu 期权与资金流处理模块
负责期权链、资金流向、基本面数据等功能
"""

import asyncio
import logging
import math
import time
from typing import Any, Dict, List, Optional

import pandas as pd
from futu import RET_OK, SortField, SubType, WarrantRequest

from data_subservice._internal.circuit_breaker import get_cooldown_seconds
from data_subservice._internal.retry_utils import with_global_retry

from ._compat import safe_float
from .cache_manager import _CAPITAL_DIST_TTL, CacheManager
from .quote_handler import _execute_unsubscriptions

logger = logging.getLogger(__name__)


class OptionFundHandler:
    """期权与资金流处理器"""

    def __init__(self, connection_manager, cache_manager: CacheManager):
        self.conn_mgr = connection_manager
        self.cache_mgr = cache_manager

    @with_global_retry
    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:  # noqa: E501
        """获取期权链数据"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_option_chain_{market_ticker}_{expiration_date}"
        now = time.time()

        cached = self.cache_mgr.get_option_chain_cache(cache_key)
        if cached and now - cached[0] < 3600.0:
            return cached[1]

        # 未连接真实数据源：仅当 ctx 完全未初始化时，尝试惰性自愈重连一次 (BE-ARCH)
        # ⚠️ 2026-08-13 修复：不再以 status != CONNECTED 为条件裸裸调 connect()。
        # watchdog 在探针失败时把 status 标为 DISCONNECTED 但保留 ctx 对象，此处若
        # 抢建连会触发 connect() 覆盖式 new ctx → futu 回调线程泄漏 (实测 35min 814 线程)。
        # 故只在 quote_ctx is None (从未初始化) 时建连；断线态交给 watchdog 重连。
        if self.conn_mgr.quote_ctx is None:
            logger.warning("[OptionFundHandler] FutuService 未初始化，尝试惰性自愈连接 OpenD")
            try:
                await asyncio.to_thread(self.conn_mgr.connect)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[OptionFundHandler] 惰性连接异常: {e}")
            if self.conn_mgr.quote_ctx is None:
                return {
                    "status": "error",
                    "message": "数据源已死，无法分析：期权链数据源不可用（Futu OpenD 未连接）",
                }

        if self.conn_mgr.status != "CONNECTED":
            # 交给 watchdog 重连，这里不抢建连以避免线程泄漏
            return {
                "status": "error",
                "message": "期权链数据源暂不可用（Futu OpenD 重连中，请稍后重试）",
            }

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        if not expiration_date:
            ret, raw_date_data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_expiration_date, market_ticker
            )
            if ret != RET_OK or not isinstance(raw_date_data, pd.DataFrame) or raw_date_data.empty:  # noqa: E501
                logger.warning(
                    f"[OptionFundHandler] get_option_expiration_date 失败: ticker={market_ticker} "
                    f"ret={ret} data={str(raw_date_data)[:300]}"
                )
                return {
                    "status": "error",
                    "message": f"无法获取到期日列表: {raw_date_data}",
                }  # noqa: E501
            expiration_date = str(raw_date_data["strike_time"].iloc[0]).split(" ")[0]

        ret, chain_data = await asyncio.to_thread(
            self.conn_mgr.quote_ctx.get_option_chain,
            market_ticker,
            start=expiration_date,
            end=expiration_date,
        )
        if ret != RET_OK or not isinstance(chain_data, pd.DataFrame) or chain_data.empty:  # noqa: E501
            logger.warning(
                f"[OptionFundHandler] get_option_chain 失败: ticker={market_ticker} "
                f"expiration={expiration_date} ret={ret} data={str(chain_data)[:300]}"
            )
            return {"status": "error", "message": f"期权链获取失败: {chain_data}"}

        # 补充 IV / Greeks / 买卖价 / 量仓：Futu get_option_chain 仅返回期权链基本信息
        # (option_code/strike_price/option_type 等)，不含 option_implied_volatility 等字段。
        # 需对期权代码列表批量调 get_market_snapshot 拉快照，再按 option_code 合并回链数据，
        # 否则 compress_chain_data 提取的 implied_volatility/delta/gamma 等全为 null。
        chain_data, enrich_ok = await self._enrich_option_chain_snapshot(market_ticker, chain_data)

        result = self.cache_mgr.compress_chain_data(chain_data, expiration_date)
        # 快照补充失败：响应外层标记 degraded，让前端明确显示"IV/Greeks 快照补充失败"
        # 而非把 null IV 当成"数据源本来就没 IV"（避免空白曲面误导）。
        if not enrich_ok and result.get("status") == "success":
            result["degraded"] = True
            result["degraded_message"] = (
                "IV/Greeks 快照补充失败（get_market_snapshot 不可用），期权合约可用但 IV/Greeks 为空"
            )
        if result.get("status") == "success":
            self.cache_mgr.set_option_chain_cache(cache_key, time.time(), result)
        return result

    # ── F3: 期权策略 + 期权波动率（G4 支撑）─────────────────────────────
    @staticmethod
    def _is_option_code(code: str) -> bool:
        """判定 code 是否为期权合约代码（而非正股/ETF/指数）。

        Futu 期权 code 形如 ``US.AAPL260417C00190000``（正股. + 6 位日期
        + C/P + 8 位行权价），正股形如 ``US.AAPL`` / ``HK.00700``。
        用于 F3-2 入参互斥校验：两接口入参正好相反，传错需报可读错误。
        """
        if not code or "." not in code:
            return False
        tail = code.split(".", 1)[1]
        # 正股/ETF/指数：纯字母或数字（如 AAPL / 00700），无日期+CP 结构
        import re

        return bool(re.search(r"\d{6}[CP]\d+", tail))

    @with_global_retry
    async def get_option_strategy(
        self,
        ticker: str,
        strategy_type: str = "STRANGLE",
        spread: int = 5,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """F3-1 期权策略组合（入参必须为正股/ETF/指数，非期权 code）。

        get_option_strategy(underlying, option_strategy=, spread=) → (ret, data)
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        # F3-2 入参互斥校验：此接口要求正股/ETF/指数
        if self._is_option_code(market_ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "message": (
                    "get_option_strategy 需传入正股/ETF/指数代码（如 US.AAPL），"
                    f"而非期权合约代码（{market_ticker}）。期权波动率请用 get_option_volatility。"
                ),
            }

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            from futu import OptionStrategyType

            strat = getattr(OptionStrategyType, str(strategy_type).upper(), OptionStrategyType.STRANGLE)
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_strategy,
                market_ticker,
                option_strategy=strat,
                spread=int(spread),
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"期权策略获取失败: {data}",
                    "code": market_ticker,
                }

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "strategy_type": str(strategy_type).upper(),
                "spread": int(spread),
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_strategy 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    @staticmethod
    def _build_option_legs(legs: Any) -> Optional[List[Any]]:
        """把 [{code, action, quantity}] dict 列表转成 futu OptionStrategyLeg 对象列表。

        futu 10.10: get_option_quote / get_option_strategy_analysis 的 option_legs
        每个元素必须是 OptionStrategyLeg 对象（含 code/action/quantity 三字段），
        传入字符串会报 'each item in option_legs must be OptionStrategyLeg'。
        """
        from futu import OptionStrategyLeg

        if not isinstance(legs, (list, tuple)) or len(legs) == 0:
            return None
        built = []
        for leg in legs:
            if isinstance(leg, OptionStrategyLeg):
                built.append(leg)
                continue
            if not isinstance(leg, dict):
                return None
            code = leg.get("code")
            if not code:
                return None
            o = OptionStrategyLeg()
            o.code = str(code)
            o.action = str(leg.get("action", "BUY")).upper()
            o.quantity = int(leg.get("quantity", 1))
            built.append(o)
        return built

    @with_global_retry
    async def get_option_strategy_analysis(
        self,
        legs: Any,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.2 期权损益分析（组合策略盈亏决策）。

        get_option_strategy_analysis(option_legs) → (ret, DataFrame)，
        option_legs 为 OptionStrategyLeg 列表（[{code, action, quantity}]）。
        实测返回列: code / name / option_strategy / max_profit / max_loss /
        breakeven_points / prob_of_profit / delta / theta。
        ⚠️ 损益字段（盈亏平衡点/最大盈亏）必须来自本接口真实返回，严禁 Black-Scholes 近似。
        """
        built = self._build_option_legs(legs)
        if not built:
            return {
                "status": "error",
                "source": "futu",
                "message": "option_legs 须为非空 [{code, action, quantity}] 列表（组合至少 1 腿）",
            }
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_option_strategy_analysis, built)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"期权损益分析失败: {data}"}
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = []
            for r in rows:
                item = {
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "option_strategy": r.get("option_strategy"),
                    "bid1": r.get("bid1"),
                    "ask1": safe_float(r.get("ask1")),
                    "max_profit": safe_float(r.get("max_profit")),
                    "max_loss": safe_float(r.get("max_loss")),
                    "breakeven_points": r.get("breakeven_points"),
                    "prob_of_profit": safe_float(r.get("prob_of_profit")),
                    "delta": safe_float(r.get("delta")),
                    "theta": safe_float(r.get("theta")),
                }
                clean.append(item)
            return {
                "status": "success",
                "source": "futu",
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_strategy_analysis 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    @with_global_retry
    async def get_option_quote(
        self,
        legs: Any,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.2 期权快照（组合腿的实时行情 + Greeks + 盈亏决策字段）。

        get_option_quote(option_legs) → (ret, DataFrame)。
        实测返回 38 列: price/implied_volatility/delta/gamma/vega/theta/rho/
        breakeven_point/prob_of_profit/leverage_ratio/effective_gearing 等。
        高频行情，短 TTL 缓存（与期权链一致，5 分钟级）。
        """
        built = self._build_option_legs(legs)
        if not built:
            return {
                "status": "error",
                "source": "futu",
                "message": "option_legs 须为非空 [{code, action, quantity}] 列表（组合至少 1 腿）",
            }
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_option_quote, built)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"期权快照获取失败: {data}"}
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: (safe_float(v) if isinstance(v, (int, float)) else v) for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_quote 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    @with_global_retry
    async def get_option_volatility(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """F3-1 期权波动率（入参必须为期权合约代码，非正股）。

        get_option_volatility(opt_code) → (ret, data)。若只给正股，自动从
        期权链取首个样本 code（graceful fallback，但仍优先尊重显式期权 code）。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        # F3-2 入参互斥校验：此接口要求期权 code
        if not self._is_option_code(market_ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "message": (
                    "get_option_volatility 需传入期权合约代码（如 US.AAPL260417C00190000），"
                    f"而非正股代码（{market_ticker}）。期权策略请用 get_option_strategy。"
                ),
            }

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_option_volatility, market_ticker)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"期权波动率获取失败: {data}",
                    "code": market_ticker,
                }

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_volatility 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    # ── P0.5.2: 标的已实现波动率 HV（正股/ETF 代码）──────────────────────────
    @with_global_retry
    async def get_option_underlying_his_volatility(
        self,
        ticker: str,
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.2 标的已实现波动率 HV（时间序列，正股/ETF/指数代码入参）。

        get_option_underlying_his_volatility(code, begin_time, end_time) → (ret, df1, df2)。
        实测 df1 列: code/name/time/timestamp/iv/hv/underlying_price。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }
        try:
            ret, data, _ = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_underlying_his_volatility, code, "NORMAL", begin_time, end_time, None
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"HV 获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [
                {
                    "time": r.get("time"),
                    "iv": safe_float(r.get("iv")),
                    "hv": safe_float(r.get("hv")),
                    "underlying_price": safe_float(r.get("underlying_price")),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_underlying_his_volatility 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P0.5.2: 标的总览（IV/IV_RANK/HV 多周期，Put/Call 量仓）───────────────
    @with_global_retry
    async def get_option_underlying_overview(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.2 标的期权总览（正股/ETF 代码）。

        get_option_underlying_overview(code_list) → (ret, DataFrame)。
        实测列: code/name/call_volume/put_volume/call_open_interest/put_open_interest/
        iv/iv_rank/iv_percentile/pre_iv/hv_30d~hv_365d(+percentile)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }
        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_option_underlying_overview, [code])
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"标的总览获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: (safe_float(v) if isinstance(v, (int, float)) else v) for k, v in r.items()} for r in rows]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_underlying_overview 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P0.5.3: 期权市场统计（Put/Call 比，市场级）──────────────────────────
    @with_global_retry
    async def get_option_market_statistic(
        self,
        option_market: str = "US_SECURITY",
        data_type: str = "VOLUME",
        begin_time: Optional[str] = None,
        end_time: Optional[str] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.3 期权市场 Put/Call 比（市场级情绪指标）。

        get_option_market_statistic(option_market, data_type, begin_time, end_time)
        → (ret, df1, df2)。实测 df1 列: time/timestamp/call_value/put_value/total_value/ratio。
        option_market 有效值: US_SECURITY/HK_SECURITY/US_INDEX/HK_INDEX；
        data_type 有效值: VOLUME/OPEN_INTEREST。
        """
        from futu import OptionMarket, OptionStatisticDataType

        mkt = getattr(OptionMarket, str(option_market).upper(), OptionMarket.US_SECURITY)
        dtyp = getattr(OptionStatisticDataType, str(data_type).upper(), OptionStatisticDataType.VOLUME)
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}
        try:
            ret, data, _ = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_market_statistic, mkt, dtyp, begin_time, end_time, None
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"期权市场统计获取失败: {data}"}
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [
                {
                    "time": r.get("time"),
                    "call_value": safe_float(r.get("call_value")),
                    "put_value": safe_float(r.get("put_value")),
                    "total_value": safe_float(r.get("total_value")),
                    "put_call_ratio": safe_float(r.get("ratio")),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "option_market": str(option_market).upper(),
                "data_type": str(data_type).upper(),
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_market_statistic 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    async def _enrich_option_chain_snapshot(self, market_ticker: str, chain_data: pd.DataFrame) -> tuple:
        """用 get_market_snapshot 为期权链补充 IV / Greeks / 买卖价 / 量仓。

        Futu get_option_chain 返回的 DataFrame 不含 option_implied_volatility / option_delta
        等字段（这些仅由 get_market_snapshot 提供），导致 compress_chain_data 提取的
        implied_volatility / delta / gamma / vega / theta / bid / ask / volume /
        open_interest 全为 null。此处按 option_code 批量拉快照并合并回链数据。

        快照失败不阻断主流程：返回 (原始 chain_data, ok=False)，字段保持 null，
        由调用方在响应外层标记 degraded:true + degraded_message，让前端明确区分
        "快照补充失败"而非"数据源本来就没 IV"（避免空白曲面误导）。
        返回格式：(chain_data, ok: bool)。
        """
        try:
            # 兼容 Futu 列名：期权代码列可能是 option_code 或 code
            code_col = (
                "option_code"
                if "option_code" in chain_data.columns
                else ("code" if "code" in chain_data.columns else None)
            )
            if not code_col:
                return chain_data, False
            option_codes = chain_data[code_col].astype(str).tolist()
            if not option_codes:
                return chain_data, False

            ret, snap_df = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_market_snapshot, option_codes)
            if ret != RET_OK or not isinstance(snap_df, pd.DataFrame) or snap_df.empty:
                logger.warning(
                    f"[OptionFundHandler] get_market_snapshot 补充期权快照失败: "
                    f"ticker={market_ticker} ret={ret} data={str(snap_df)[:200]}"
                )
                return chain_data, False

            # 快照以 code 列标识期权代码，与链数据的 code 列对齐合并
            snap_col = "code" if "code" in snap_df.columns else snap_df.columns[0]
            snap_df = snap_df.rename(columns={snap_col: code_col})
            # 仅保留链数据没有的快照列，避免覆盖 code/strike_price 等
            extra_cols = [c for c in snap_df.columns if c not in chain_data.columns]
            extra_cols.append(code_col)
            snap_extra = snap_df[extra_cols].drop_duplicates(subset=code_col)
            return chain_data.merge(snap_extra, on=code_col, how="left"), True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[OptionFundHandler] 补充期权快照异常: {e}")
            return chain_data, False

    @with_global_retry
    async def get_fund_flow(self, ticker: str, format_ticker_func=None, is_unsupported_func=None) -> Dict[str, Any]:
        """获取资金流向数据（带熔断机制）"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_fund_flow_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_fund_flow_cache(cache_key)
        if cached and now - cached[0] < 60.0:
            return cached[1]

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_fund_flow(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 🚨 全局熔断拦截：冷却期内返回错误 (零幻觉 — 绝不用 Mock 填充真实资金流)
        if time.time() < self.cache_mgr.ff_circuit_breaker_until:
            if __import__("os").getenv("QUANT_ENV") == "development":
                from .mock_provider import MockProvider

                return MockProvider.mock_fund_flow(ticker)
            return {
                "status": "error",
                "message": "资金流向接口处于熔断冷却期，暂不可用（请稍后再试）",
            }

        if self.cache_mgr.ff_lock is None:
            self.cache_mgr.ff_lock = asyncio.Lock()

        async with self.cache_mgr.ff_lock:
            # 全局限流排队：严格控制资金流向请求间隔
            elapsed = time.time() - self.cache_mgr.last_ff_time
            if elapsed < 0.6:
                await asyncio.sleep(0.6 - elapsed)
            self.cache_mgr.last_ff_time = time.time()

            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_capital_distribution, market_ticker)

        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            if "频率太高" in str(data) or "frequency" in str(data).lower():
                print(f"🚨 [Futu] 资金流向触发限流熔断！接口将强制全局休眠 60 秒以释放压力 ({data})")  # noqa: E501
                self.cache_mgr.ff_circuit_breaker_until = time.time() + get_cooldown_seconds()
                if __import__("os").getenv("QUANT_ENV") == "development":
                    from .mock_provider import MockProvider

                    res = MockProvider.mock_fund_flow(ticker)
                    self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
                    return res
                # 生产环境零幻觉：返回错误而非假数据，并缓存错误避免短时重复击穿
                res = {"status": "error", "message": "资金流向触发限流熔断，暂不可用（接口休眠中）"}
                self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
                return res

            res = {"status": "error", "message": f"资金流向数据获取失败: {data}"}
            self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), res)
            return res

        row = data.iloc[0]
        main_in = safe_float(row.get("capital_in_super", 0)) + safe_float(row.get("capital_in_big", 0))  # noqa: E501
        main_out = safe_float(row.get("capital_out_super", 0)) + safe_float(row.get("capital_out_big", 0))  # noqa: E501

        broker_data, order_book_data = None, None
        if market_ticker.startswith("HK."):
            # LRU 订阅池管理：检查并确保容量
            need_sub = []
            for st in [SubType.BROKER, SubType.ORDER_BOOK]:
                if not self.cache_mgr.has_topic(market_ticker, st):
                    need_sub.append(st)

            if need_sub:
                evicted = self.cache_mgr.ensure_capacity(needed=len(need_sub))
                await _execute_unsubscriptions(self.conn_mgr, self.cache_mgr, evicted)

                sub_ret, sub_err = await asyncio.to_thread(
                    self.conn_mgr.quote_ctx.subscribe,
                    [market_ticker],
                    need_sub,
                    subscribe_push=True,  # 开启推送，盘口/经纪商变动实时推送  # noqa: E501
                )
                if sub_ret == RET_OK:
                    for st in need_sub:
                        self.cache_mgr.touch_topic(market_ticker, st)
            else:
                sub_ret = RET_OK  # 已订阅，跳过

            if sub_ret == RET_OK:
                for _ in range(3):
                    await asyncio.sleep(0.3)
                    res = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_broker_queue, market_ticker)
                    bid_df, ask_df = (
                        (res[1], res[2])
                        if res and res[0] == RET_OK and len(res) > 2
                        else (pd.DataFrame(), pd.DataFrame())
                    )  # noqa: E501
                    if (isinstance(bid_df, pd.DataFrame) and not bid_df.empty) or (
                        isinstance(ask_df, pd.DataFrame) and not ask_df.empty
                    ):
                        break

                if (isinstance(bid_df, pd.DataFrame) and not bid_df.empty) or (
                    isinstance(ask_df, pd.DataFrame) and not ask_df.empty
                ):

                    def parse_brokers(df):
                        return (
                            df[df.columns[1]].dropna().unique().tolist()[:10]
                            if isinstance(df, pd.DataFrame) and not df.empty
                            else []
                        )  # noqa: E501

                    def fmt_q(q):
                        return ", ".join(map(str, q)) if q else "暂无"

                    bid_q, ask_q = parse_brokers(bid_df), parse_brokers(ask_df)
                    broker_data = {
                        "bid_brokers_queue_str": fmt_q(bid_q),
                        "ask_brokers_queue_str": fmt_q(ask_q),
                    }

                ret_ob, ob_data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_order_book, market_ticker)
                if ret_ob == RET_OK and isinstance(ob_data, dict):
                    bids, asks = ob_data.get("Bid", []), ob_data.get("Ask", [])
                    bid1 = {"price": safe_float(bids[0][0]), "volume": int(bids[0][1])} if bids else None  # noqa: E501
                    ask1 = {"price": safe_float(asks[0][0]), "volume": int(asks[0][1])} if asks else None  # noqa: E501
                    order_book_data = {"bid1": bid1, "ask1": ask1}

        def _fmt_money(val: float) -> str:
            if abs(val) >= 1_0000_0000:
                return f"{val / 1_0000_0000:.2f}亿"  # noqa: E701
            if abs(val) >= 1_0000:
                return f"{val / 1_0000:.2f}万"  # noqa: E701
            return f"{val:.2f}"

        result = {
            "status": "success",
            "ticker": ticker,
            "main_fund_net_inflow": main_in - main_out,
            "main_fund_net_inflow_str": _fmt_money(main_in - main_out),
            "broker_queue": broker_data,
            "order_book_level_1": order_book_data,
        }
        self.cache_mgr.set_fund_flow_cache(cache_key, time.time(), result)
        return result

    # ── F4-1: 主力筹码分层（补 FUND_FLOW 8 档 in/out）────────────────────
    @with_global_retry
    async def get_capital_distribution(
        self, ticker: str, format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取主力筹码分层（8 档 in/out 完整明细，非聚合净流入）。

        支撑 G3 主力/散户背离信号。get_capital_distribution(code) → (ret, data) 二元组。
        带 L1 内存缓存(5 分钟)，避免每次穿透 OpenD 资金分布接口(与资金流同源, 有限流风险)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        # 💡 L1 内存缓存命中直接返回(5 分钟 TTL, 与资金流同源降频)
        cache_key = f"futu_capital_dist_{market_ticker}"
        now = time.time()
        cached = self.cache_mgr.get_capital_dist_cache(cache_key)
        if cached and now - cached[0] < _CAPITAL_DIST_TTL:
            return cached[1]

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_capital_distribution, market_ticker)
            if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"资金分层获取失败: {data}",
                    "code": market_ticker,
                }

            row = data.iloc[0]
            layers = {}
            for lvl in ("super", "big", "mid", "small"):
                cap_in = safe_float(row.get(f"capital_in_{lvl}"))
                cap_out = safe_float(row.get(f"capital_out_{lvl}"))
                layers[lvl] = {
                    "in": cap_in,
                    "out": cap_out,
                    "net": (cap_in - cap_out) if cap_in is not None and cap_out is not None else None,
                }
            # 主力 = super + big；散户 = mid + small
            main_net = (layers["super"]["net"] or 0) + (layers["big"]["net"] or 0)
            retail_net = (layers["mid"]["net"] or 0) + (layers["small"]["net"] or 0)
            update_time = row.get("update_time")

            res = {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "update_time": str(update_time) if update_time is not None else None,
                "layers": layers,
                "main_net": main_net,  # 主力净额 = (super+big) in-out
                "retail_net": retail_net,  # 散户净额 = (mid+small) in-out
                # G3 背离信号：主力净流入 ∧ 散户净流出（或反向）
                "divergence": (
                    "main_in_retail_out"
                    if main_net > 0 and retail_net < 0
                    else "main_out_retail_in"
                    if main_net < 0 and retail_net > 0
                    else "aligned"
                ),
            }
            # 写入 L1 缓存, 避免高频穿透 OpenD 资金分布接口
            self.cache_mgr.set_capital_dist_cache(cache_key, now, res)
            return res
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_capital_distribution 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    # ── F4-4: 分析师共识（卖方观点，非事实）────────────────────────────
    @with_global_retry
    async def get_research_analyst_consensus(
        self, ticker: str, format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取分析师共识（评级分布 / 目标价中位数）。

        ⚠️ 红线：共识是卖方观点而非事实，返回结构显式标注 ``source=futu_consensus``
        与 ``is_third_party_expectation=True``，禁止当预测结论输出（G7 引用约束）。
        get_research_analyst_consensus(code) → (ret, data) 二元组。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_research_analyst_consensus, market_ticker)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"分析师共识获取失败: {data}",
                    "code": market_ticker,
                }

            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [{k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()} for r in rows]

            return {
                "status": "success",
                "source": "futu_consensus",
                "is_third_party_expectation": True,
                "ticker": ticker,
                "code": market_ticker,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_research_analyst_consensus 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    @with_global_retry
    async def get_fundamental(self, ticker: str, format_ticker_func=None, is_unsupported_func=None) -> Dict[str, Any]:
        """获取基本面数据"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        cache_key = f"futu_fundamental_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_fundamental_cache(cache_key)
        if cached and now - cached[0] < 3600.0:
            return cached[1]

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            from .mock_provider import MockProvider

            return MockProvider.mock_fundamental(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_market_snapshot, [market_ticker])
        if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
            res = {"status": "error", "message": f"基本面数据获取失败: {data}"}
            self.cache_mgr.set_fundamental_cache(cache_key, time.time(), res)
            return res

        row = data.iloc[0]

        def _snap_float(key: str) -> Optional[float]:
            """snapshot 数值取值：0/NaN 视为无数据返回 None；负值保留（如亏损股 PE 为负是有效信息）。

            ⚠️ futu 10.10 get_market_snapshot 实测列名为 pb_ratio/total_market_val/pe_ttm_ratio/
            earning_per_share/net_asset_per_share（无 pb_rate/market_val/dividend_yield 列，
            row.get 对不存在列安全降级为默认值）。
            """
            v = safe_float(row.get(key, 0.0))
            if v == 0.0 or (isinstance(v, float) and math.isnan(v)):
                return None
            return v

        _div = safe_float(row.get("dividend_yield", 0.0))
        result = {
            "status": "success",
            "data": {
                "ticker": ticker,
                "company_name": str(row.get("name", "")),
                "trailing_PE": _snap_float("pe_ratio"),
                "pe_ttm": _snap_float("pe_ttm_ratio"),
                "price_to_book": _snap_float("pb_ratio"),
                "earnings_per_share": _snap_float("earning_per_share"),
                "net_asset_per_share": _snap_float("net_asset_per_share"),
                "market_cap": _snap_float("total_market_val"),
                "dividend_yield": f"{_div}%" if _div > 0 else None,
            },
        }
        result["data"] = {k: v for k, v in result["data"].items() if v is not None}
        self.cache_mgr.set_fundamental_cache(cache_key, time.time(), result)
        return result

    # ── F5: 十大买卖经纪商（经纪版面，盘口 tab）──────────────────────────
    @with_global_retry
    async def get_top_brokers(
        self, ticker: str, days_before: int = 0, format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取十大买卖经纪商（净买/净卖两组）。

        futu `get_top_ten_buy_sell_brokers` 仅支持港股正股/基金（实测 US 标的返回
        "只支持港股正股和基金"）。US 等其它市场 futu 无经纪商明细接口，直接标记
        unsupported，避免误报为数据源故障/STALE。
        """
        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        # 仅港股支持经纪商明细；其它市场（US 等）futu 无此接口，提前返回 unsupported
        if not market_ticker.upper().startswith("HK."):
            return {
                "status": "unsupported",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "message": "Futu 经纪商明细仅支持港股，当前市场不支持",
            }

        cache_key = f"futu_top_brokers_{market_ticker}_{days_before}"
        now = time.time()
        cached = self.cache_mgr.get_top_brokers_cache(cache_key)
        if cached and now - cached[0] < _CAPITAL_DIST_TTL:
            return cached[1]

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_top_ten_buy_sell_brokers, market_ticker, days_before
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"十大经纪商获取失败: {data}",
                    "code": market_ticker,
                }

            # 💡 DIST-SEC-02 教训：futu yfinance 等历史 K 线 columns 为 MultiIndex，
            # 单层键访问会错位静默丢失。这里统一拍平为第一级列名。
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            buy_list, sell_list = [], []
            for _, row in data.iterrows():
                btype = str(row.get("buy_sell_type", "")).upper()
                item = {
                    "broker_name": row.get("broker_name"),
                    "avg_price": safe_float(row.get("avg_price")),
                    "net_vol": safe_float(row.get("net_vol")),
                    "total_vol": safe_float(row.get("total_vol")),
                    "total_turnover": safe_float(row.get("total_turnover")),
                }
                if btype == "BUY":
                    buy_list.append(item)
                elif btype == "SELL":
                    sell_list.append(item)

            res = {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "days_before": days_before,
                "is_real_time": bool(safe_float(row.get("is_real_time", 0)) if "is_real_time" in data.columns else 0),
                "buy_brokers": buy_list,
                "sell_brokers": sell_list,
            }
            self.cache_mgr.set_top_brokers_cache(cache_key, now, res)
            return res
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_top_brokers 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    # ── F6: 个股资金流向时间序列（资金流向曲线，微观 tab）───────────────────
    @with_global_retry
    async def get_capital_flow(
        self, ticker: str, period_type: str = "INTRADAY", format_ticker_func=None, is_unsupported_func=None
    ) -> Dict[str, Any]:
        """获取个股资金流入流出时间序列。

        get_capital_flow(code, period_type='INTRADAY', start, end) → (ret, data) 二元组。
        INTRADAY = 当日分时净流入；返回 data_time_str / capital_in_flow / capital_out_flow 等。
        带 L1 缓存(2 分钟)，与资金流同源降频。
        """
        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker
        if not market_ticker:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        cache_key = f"futu_capital_flow_{market_ticker}_{period_type}"
        now = time.time()
        cached = self.cache_mgr.get_capital_flow_cache(cache_key)
        if cached and now - cached[0] < _CAPITAL_DIST_TTL:
            return cached[1]

        if self.conn_mgr.quote_ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": market_ticker,
            }
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": market_ticker,
            }

        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_capital_flow, market_ticker, period_type)
            if ret != RET_OK or not isinstance(data, pd.DataFrame) or data.empty:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"资金流向获取失败: {data}",
                    "code": market_ticker,
                }

            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            flow = []
            for _, row in data.iterrows():
                flow.append(
                    {
                        "time": str(row.get("data_time_str") or row.get("data_time", "")),
                        "in_flow": safe_float(row.get("capital_in_flow")),
                        "out_flow": safe_float(row.get("capital_out_flow")),
                    }
                )

            res = {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": market_ticker,
                "period_type": period_type,
                "count": len(flow),
                "flow": flow,
            }
            self.cache_mgr.set_capital_flow_cache(cache_key, now, res)
            return res
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_capital_flow 失败 %s: %s", market_ticker, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": market_ticker}

    # ── F2: 三大财务报表（G1 真基本面基座）──────────────────────────────
    # 富途 get_financials_statements 实测（2026-08-22, futu-api 10.10.7008, OpenD 在线）：
    #   statement_type 必须传【整数枚举】：1=利润表 2=资产负债表 3=现金流量表 4=关键指标
    #   financial_type 传【F10Type 字符串】：'ANNUAL' / 'QUARTERLY_ANNUAL' / 'INTERIM' / 'Q1'...
    #   返回 dict：{
    #     "next_key": "时间戳,期标识" | "",   # 非空=还有下一页（分页游标，续拉填回）
    #     "structure_list": [{"field_id":int, "display_name":"中文"}],
    #     "report_list": [{date_time, fiscal_year, financial_type, period_text,
    #                      currency_code, accounting_standards,
    #                      item_list:[{field_id, display_name, data, yoy, qoq}]}]
    #   }
    # ⚠️ 字段中文名来自 SDK 返回的 display_name（零幻觉，禁手编英文枚举映射）；
    #   旧 FINANCIAL_FIELD_MAP（英文枚举 key）已废弃——field_id 实际是整数，永远命中不到。
    # 对外契约：statement_type 接受语义字符串(income/balance_sheet/cash_flow/main_index)或整数 1~4。

    # 对外语义字符串 -> SDK 整数枚举（兼容历史调用传字符串）
    _STMT_TYPE_MAP = {
        "income": 1,
        "income_statement": 1,
        "profit": 1,
        "balance": 2,
        "balance_sheet": 2,
        "cash_flow": 3,
        "cashflow": 3,
        "cashflow_statement": 3,
        "main_index": 4,
        "key_indicators": 4,
        "mainindex": 4,
    }

    @with_global_retry
    async def get_financials_statements(
        self,
        ticker,
        statement_type=None,
        financial_type=None,
        currency_code=None,
        num=None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取三大财务报表（资产负债表/利润表/现金流量表/关键指标）。

        入参:
          statement_type: 整数 1/2/3/4，或语义字符串 income/balance_sheet/cash_flow/main_index
                          （None 默认 2=资产负债表）
          financial_type: F10Type 字符串 ANNUAL/QUARTERLY_ANNUAL/INTERIM/Q1...（None 默认 ANNUAL）
          currency_code:  ISO 4217（None 返回原始货币）
          num:            期望返回的报告期数（分页续拉直到满足或 next_key 空，默认 4）
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "标的非港股/美股/沪深，富途不支持",
            }
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        # statement_type 归一为整数枚举（1~4）
        if statement_type is None:
            stmt_int = 2
        elif isinstance(statement_type, int):
            stmt_int = statement_type
        else:
            stmt_int = self._STMT_TYPE_MAP.get(str(statement_type).strip().lower())
            if stmt_int is None:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"不支持的 statement_type: {statement_type!r}（支持 income/balance_sheet/cash_flow/main_index 或 1~4）",
                    "code": code,
                }

        ft = financial_type or "ANNUAL"
        want = int(num) if num else 4

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}

        cache_key = f"futu_financials_{code}_{stmt_int}_{ft}_{currency_code or 'orig'}"
        cached = self.cache_mgr.get_financials_cache(cache_key)
        if cached is not None:
            return cached[1]

        try:
            reports: list = []
            next_key = ""
            pages = 0
            # 分页续拉：每次拉满 50（API 上限），累计达到 want 或 next_key 空则停
            while len(reports) < want and pages < 20:
                ret, data = await asyncio.to_thread(
                    ctx.get_financials_statements, code, stmt_int, ft, currency_code, next_key, 50
                )
                if ret != RET_OK:
                    return {"status": "error", "source": "futu", "ticker": ticker, "message": str(data), "code": code}
                if not isinstance(data, dict):
                    break
                reports.extend(data.get("report_list", []) or [])
                next_key = data.get("next_key") or ""
                pages += 1
                if not next_key:
                    break

            # 字段中文名来自 SDK item_list.display_name（零幻觉，不手编）
            periods = []
            for rep in reports[:want]:
                items = []
                for it in rep.get("item_list", []) or []:
                    items.append(
                        {
                            "field_id": it.get("field_id"),
                            "name_cn": it.get("display_name") or it.get("field_id"),
                            "value": it.get("data"),
                            "yoy": it.get("yoy"),
                            "qoq": it.get("qoq"),
                        }
                    )
                periods.append(
                    {
                        "fiscal_year": rep.get("fiscal_year"),
                        "financial_type": rep.get("financial_type"),
                        "period_text": rep.get("period_text"),
                        "date_time_str": rep.get("date_time_str"),
                        "currency_code": rep.get("currency_code"),
                        "accounting_standards": rep.get("accounting_standards"),
                        "items": items,
                    }
                )

            result = {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "statement_type": stmt_int,
                "financial_type": ft,
                "currency_code": currency_code,
                "count": len(periods),
                "data": periods,
            }
            self.cache_mgr.set_financials_cache(cache_key, time.time(), result)
            return result
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_financials_statements 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── F2: 估值明细（G1 真基本面基座）──────────────────────────────────
    async def get_valuation_detail(
        self,
        ticker,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取估值明细（PE/PB/股息率/市值等逐指标）。"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "标的非港股/美股/沪深，富途不支持",
            }
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}

        try:
            ret, data = ctx.get_valuation_detail(code)
            if ret != RET_OK:
                return {"status": "error", "source": "futu", "ticker": ticker, "message": str(data), "code": code}

            if hasattr(data, "to_dict"):
                rows = data.to_dict("records")
            else:
                rows = list(data)
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(rows),
                "data": rows,
            }
        except Exception as e:
            logger.error(f"❌ get_valuation_detail 失败 {code}: {e}")
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_warrant_chain(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取港股窝轮/牛熊证链数据（用于市场多空情绪分析）"""
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "message": "富途原生不支持该大类资产"}

        market_ticker = format_ticker_func(ticker) if format_ticker_func else ticker

        # 仅港股支持窝轮
        if not market_ticker.startswith("HK."):
            return {"status": "error", "message": f"窝轮/牛熊证仅支持港股标的，当前: {ticker}"}

        cache_key = f"futu_warrant_chain_{market_ticker}"
        now = time.time()

        cached = self.cache_mgr.get_option_chain_cache(cache_key)
        if cached and now - cached[0] < 300.0:  # 5分钟缓存
            return cached[1]

        # 开发环境 Mock
        if self.conn_mgr.status != "CONNECTED" and __import__("os").getenv("QUANT_ENV") == "development":  # noqa: E501
            return self._mock_warrant_chain(ticker)

        if not self.conn_mgr.quote_ctx:
            return {"status": "error", "message": "FutuService 未连接"}

        # 按成交额降序，拉取最活跃的窝轮/牛熊证
        req = WarrantRequest()
        req.sort_field = SortField.TURNOVER
        req.ascend = False
        req.num = 200

        ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_warrant, market_ticker, req)
        if ret != RET_OK:
            return {"status": "error", "message": f"窝轮数据获取失败: {data}"}

        warrant_df, last_page, all_count = data
        if not isinstance(warrant_df, pd.DataFrame) or warrant_df.empty:
            return {"status": "error", "message": f"{ticker} 无可用窝轮/牛熊证数据"}

        result = self._compress_warrant_data(warrant_df, ticker, all_count)
        self.cache_mgr.set_option_chain_cache(cache_key, time.time(), result)
        return result

    def _compress_warrant_data(self, df: pd.DataFrame, ticker: str, all_count: int) -> Dict[str, Any]:
        """将窝轮 DataFrame 压缩为结构化摘要 + 情绪统计"""
        warrants = []
        call_count, put_count, bull_count, bear_count = 0, 0, 0, 0
        call_turnover, put_turnover = 0.0, 0.0

        for _, row in df.iterrows():
            wrt_type = str(row.get("type", ""))
            turnover = safe_float(row.get("turnover", 0))

            # 统计多空分布
            if wrt_type == "CALL":
                call_count += 1
                call_turnover += turnover
            elif wrt_type == "PUT":
                put_count += 1
                put_turnover += turnover
            elif wrt_type == "BULL":
                bull_count += 1
            elif wrt_type == "BEAR":
                bear_count += 1

            warrants.append(
                {
                    "code": str(row.get("stock", "")),
                    "name": str(row.get("name", "")),
                    "type": wrt_type,
                    "issuer": str(row.get("issuer", "")),
                    "strike_price": safe_float(row.get("strike_price", 0)),
                    "cur_price": safe_float(row.get("cur_price", 0)),
                    "premium": safe_float(row.get("premium", 0)),
                    "leverage": safe_float(row.get("leverage", 0)),
                    "delta": safe_float(row.get("delta", 0)),
                    "implied_volatility": safe_float(row.get("implied_volatility", 0)),
                    "turnover": turnover,
                    "volume": int(safe_float(row.get("volume", 0))),
                    "maturity_time": str(row.get("maturity_time", "")),
                    "street_rate": safe_float(row.get("street_rate", 0)),
                    "recovery_price": safe_float(row.get("recovery_price", 0)),
                }
            )

        # 情绪摘要
        total_call_put = call_count + put_count
        call_ratio = round(call_count / total_call_put * 100, 1) if total_call_put > 0 else 50.0
        total_bull_bear = bull_count + bear_count
        bull_ratio = round(bull_count / total_bull_bear * 100, 1) if total_bull_bear > 0 else 50.0

        sentiment = (
            "偏多" if call_ratio > 60 and bull_ratio > 60 else "偏空" if call_ratio < 40 and bull_ratio < 40 else "中性"
        )

        return {
            "status": "success",
            "ticker": ticker,
            "total_count": all_count,
            "sentiment_summary": {
                "call_count": call_count,
                "put_count": put_count,
                "bull_count": bull_count,
                "bear_count": bear_count,
                "call_ratio_pct": call_ratio,
                "bull_ratio_pct": bull_ratio,
                "call_turnover": call_turnover,
                "put_turnover": put_turnover,
                "sentiment": sentiment,
            },
            "warrants": warrants[:50],  # 返回前50只最活跃的
        }

    @staticmethod
    def _mock_warrant_chain(ticker: str) -> Dict[str, Any]:
        """开发环境 Mock 窝轮数据"""
        return {
            "status": "success",
            "ticker": ticker,
            "total_count": 4,
            "sentiment_summary": {
                "call_count": 2,
                "put_count": 1,
                "bull_count": 1,
                "bear_count": 0,
                "call_ratio_pct": 66.7,
                "bull_ratio_pct": 100.0,
                "call_turnover": 5_000_000.0,
                "put_turnover": 2_000_000.0,
                "sentiment": "偏多",
            },
            "warrants": [
                {
                    "code": "HK.19001",
                    "name": "MOCK_CALL@EC2612",
                    "type": "CALL",
                    "issuer": "MB",
                    "strike_price": 40.0,
                    "cur_price": 0.15,
                    "premium": 12.5,
                    "leverage": 8.2,
                    "delta": 0.45,
                    "implied_volatility": 42.0,
                    "turnover": 3_000_000.0,
                    "volume": 20_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 15.0,
                    "recovery_price": 0,
                },
                {
                    "code": "HK.19002",
                    "name": "MOCK_PUT@EC2612",
                    "type": "PUT",
                    "issuer": "SG",
                    "strike_price": 35.0,
                    "cur_price": 0.08,
                    "premium": 8.3,
                    "leverage": 6.5,
                    "delta": -0.35,
                    "implied_volatility": 38.0,
                    "turnover": 2_000_000.0,
                    "volume": 15_000_000,
                    "maturity_time": "2026-12-01",
                    "street_rate": 8.0,
                    "recovery_price": 0,
                },
            ],
        }

    # ── P1.2: 分析师评级明细（INSTITUTION / ANALYST 两维）───────────────
    @with_global_retry
    async def get_research_rating_summary(
        self,
        ticker: str,
        rating_dimension_type: str = "INSTITUTION",
        uid: Optional[str] = None,
        num: Optional[int] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取分析师评级明细（机构/分析师两维, 支持翻页）。

        futu `get_research_rating_summary(code, rating_dimension_type, uid, num, next_key)`
        → (ret, dict)，dict 含 `next_key` + `inst_rating_summary_list`(INSTITUTION) 或
        `analyst_rating_summary_list`(ANALYST)。

        实测枚举: rating_dimension_type 有效值 INSTITUTION / ANALYST（带 RATING_DIMENSION_BY_ 前缀会报错）。
        ⚠️ 卖方观点（第三方预期），返回标注 is_third_party_expectation=True。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}
        if rating_dimension_type not in ("INSTITUTION", "ANALYST"):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": f"不支持的 rating_dimension_type: {rating_dimension_type!r}（支持 INSTITUTION/ANALYST）",
                "code": code,
            }

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(
                ctx.get_research_rating_summary, code, rating_dimension_type, uid, num, None
            )
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"分析师评级获取失败: {data}",
                    "code": code,
                }
            list_key = (
                "inst_rating_summary_list" if rating_dimension_type == "INSTITUTION" else "analyst_rating_summary_list"
            )
            rows = data.get(list_key, []) or []
            clean = []
            for r in rows:
                info = r.get("institution_info") if rating_dimension_type == "INSTITUTION" else r.get("analyst_info")
                if not isinstance(info, dict):
                    info = {}
                name = (
                    info.get("institution_name") if rating_dimension_type == "INSTITUTION" else info.get("analyst_name")
                )
                # 评级数据在 rating_item_list 内（含 rating/target_price/recommendation_date）
                latest_rating_item = {}
                for item in r.get("rating_item_list") or []:
                    latest_rating_item = item  # 取最近一条
                clean.append(
                    {
                        "uid": info.get("institution_uid")
                        if rating_dimension_type == "INSTITUTION"
                        else info.get("analyst_uid"),
                        "name": name,
                        "rating": latest_rating_item.get("rating"),
                        "target_price": latest_rating_item.get("target_price"),
                        "recommendation_date_str": latest_rating_item.get("recommendation_date_str"),
                        "rating_url": latest_rating_item.get("rating_url"),
                        "update_time_str": latest_rating_item.get("update_time_str"),
                    }
                )
            return {
                "status": "success",
                "source": "futu_consensus",
                "is_third_party_expectation": True,
                "ticker": ticker,
                "code": code,
                "rating_dimension_type": rating_dimension_type,
                "next_key": data.get("next_key"),
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_research_rating_summary 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P1.3: 主营构成（收入拆分，region/product 两维）─────────────────
    @with_global_retry
    async def get_financials_revenue_breakdown(
        self,
        ticker: str,
        financial_type: str = "ANNUAL",
        date: Optional[str] = None,
        currency_code: Optional[str] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取主营构成（按地区 REGION / 按产品 PRODUCT 的收入拆分）。

        futu `get_financials_revenue_breakdown(code, date, financial_type, currency_code)`
        → (ret, dict)，dict 含 period / currency_code / breakdown_list / screen_date_list。

        实测枚举: financial_type 有效值 ANNUAL/QUARTERLY/Q1/Q2/Q3/Q4 等（小写 annual 会报错）。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(
                ctx.get_financials_revenue_breakdown, code, date, financial_type, currency_code
            )
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"主营构成获取失败: {data}",
                    "code": code,
                }
            breakdowns = []
            for b in data.get("breakdown_list", []) or []:
                items = []
                for it in b.get("item_list", []) or []:
                    items.append(
                        {
                            "name": it.get("name"),
                            "main_oper_income": safe_float(it.get("main_oper_income")),
                            "ratio_pct": safe_float(it.get("ratio")),
                        }
                    )
                breakdowns.append({"type": b.get("type"), "items": items})
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "financial_type": financial_type,
                "period": data.get("period"),
                "currency_code": data.get("currency_code") or currency_code,
                "screen_date_list": data.get("screen_date_list") or [],
                "count": len(breakdowns),
                "data": breakdowns,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_financials_revenue_breakdown 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P1.4: 卖空持仓（short interest, 累计未平仓卖空）────────────────
    @with_global_retry
    async def get_short_interest(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取累计卖空持仓（short interest，美股）。

        futu `get_short_interest(code, next_key, num)` → (ret, df1, df2) 三元组：
        - df1: 逐期卖空（timestamp/shares_short/short_percent/avg_daily_share_volume/days_to_cover...）
        - df2: 聚合卖空（aggregated_short/aggregated_short_ratio...，可为空）
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            res = await asyncio.to_thread(ctx.get_short_interest, code, None, num)
            if not isinstance(res, tuple) or len(res) < 2:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"卖空持仓获取失败: {res}",
                    "code": code,
                }
            ret = res[0]
            if ret != RET_OK:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"卖空持仓获取失败: {res[1]}",
                    "code": code,
                }
            df1 = res[1] if isinstance(res[1], pd.DataFrame) else pd.DataFrame()
            df2 = res[2] if len(res) > 2 and isinstance(res[2], pd.DataFrame) else pd.DataFrame()
            rows = df1.to_dict("records") if not df1.empty else []
            clean = [
                {
                    "time": r.get("timestamp_str"),
                    "shares_short": safe_float(r.get("shares_short")),
                    "short_percent": safe_float(r.get("short_percent")),
                    "avg_daily_share_volume": safe_float(r.get("avg_daily_share_volume")),
                    "days_to_cover": safe_float(r.get("days_to_cover")),
                    "close_price": safe_float(r.get("close_price")),
                    "last_close_price": safe_float(r.get("last_close_price")),
                }
                for r in rows
            ]
            agg = df2.to_dict("records") if not df2.empty else []
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
                "aggregated": agg,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_short_interest 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P1.5: 股东持股 / 内部人交易 ────────────────────────────────────
    @with_global_retry
    async def get_shareholders_overview(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """股东概况（主要股东 / 机构 / 内部人持股概览）。

        futu `get_shareholders_overview(code)` → (ret, dict)，dict 含 main_holder(DataFrame)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_shareholders_overview, code)
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"股东概况获取失败: {data}",
                    "code": code,
                }
            main_df = data.get("main_holder")
            main_rows = []
            if isinstance(main_df, pd.DataFrame) and not main_df.empty:
                main_rows = [
                    {
                        "name": r.get("name"),
                        "holder_pct": safe_float(r.get("holder_pct")),
                        "static_date_str": r.get("static_date_str"),
                        "change_pct": safe_float(r.get("change_pct")),
                        "holder_quantity": safe_float(r.get("holder_quantity")),
                        "holder_id": r.get("holder_id"),
                    }
                    for _, r in main_df.iterrows()
                ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(main_rows),
                "data": main_rows,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_shareholders_overview 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_shareholders_holding_changes(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """股东持股变动（机构增减持明细）。

        futu `get_shareholders_holding_changes(code, next_key, num, sort_type, sort_column, filter_type)`
        → (ret, DataFrame)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_shareholders_holding_changes, code, None, num, None, None, None)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"股东持股变动获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records")
            clean = [
                {
                    "period_text": r.get("period_text"),
                    "name": r.get("name"),
                    "holder_type": r.get("holder_type"),
                    "share_change_num": safe_float(r.get("share_change_num")),
                    "share_ratio": safe_float(r.get("share_ratio")),
                    "share_ratio_change": safe_float(r.get("share_ratio_change")),
                    "share_num": safe_float(r.get("share_num")),
                    "holding_date_str": r.get("holding_date_str"),
                    "holder_id": r.get("holder_id"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_shareholders_holding_changes 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_shareholders_institutional(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """机构持股统计（机构家数/持股量/持股比例及环比）。

        futu `get_shareholders_institutional(code, next_key, num)` → (ret, DataFrame)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_shareholders_institutional, code, None, num)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"机构持股获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records")
            clean = [
                {
                    "period_text": r.get("period_text"),
                    "institution_quantity": safe_float(r.get("institution_quantity")),
                    "institution_quantity_change": safe_float(r.get("institution_quantity_change")),
                    "holder_quantity": safe_float(r.get("holder_quantity")),
                    "holder_quantity_change": safe_float(r.get("holder_quantity_change")),
                    "holder_pct": safe_float(r.get("holder_pct")),
                    "holder_pct_change": safe_float(r.get("holder_pct_change")),
                    "update_time_str": r.get("update_time_str"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_shareholders_institutional 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_shareholders_holder_detail(
        self,
        ticker: str,
        request_type: str = "ALL",
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """股东明细（按类型筛选：传统投资经理/对冲基金/VC/PE/公司等）。

        futu `get_shareholders_holder_detail(code, request_type, next_key, num, sort_column, sort_type, period_id, holder_id)`
        → (ret, DataFrame)。实测 request_type 有效值: ALL / UNCLASSIFIED / TRADITIONAL_INVESTMENT_MANAGER /
        HEDGE_FUND_MANAGER / VC_OR_PE / CORPORATE_... 等。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(
                ctx.get_shareholders_holder_detail, code, request_type, None, num, None, None, None, None
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"股东明细获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records")
            clean = [
                {
                    "name": r.get("name"),
                    "holder_pct": safe_float(r.get("holder_pct")),
                    "holder_quantity": safe_float(r.get("holder_quantity")),
                    "holder_quantity_change": safe_float(r.get("holder_quantity_change")),
                    "holder_type": r.get("holder_type"),
                    "period_text": r.get("period_text"),
                    "holding_date_str": r.get("holding_date_str"),
                    "holder_id": r.get("holder_id"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_shareholders_holder_detail 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_insider_holder_list(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """内部人（高管/董事）持股列表。

        futu `get_insider_holder_list(code, next_key, num)` → (ret, DataFrame)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_insider_holder_list, code, None, num)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"内部人持股获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records")
            clean = [
                {
                    "name": r.get("name"),
                    "title": r.get("title"),
                    "holder_quantity": safe_float(r.get("holder_quantity")),
                    "holder_pct": safe_float(r.get("holder_pct")),
                    "all_count": safe_float(r.get("all_count")),
                    "insider_bought_count": safe_float(r.get("insider_bought_count")),
                    "insider_sold_count": safe_float(r.get("insider_sold_count")),
                    "holder_id": r.get("holder_id"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_insider_holder_list 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_insider_trade_list(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """内部人交易明细（Form 4 买卖记录）。

        futu `get_insider_trade_list(code, holder_id, num, next_key)` → (ret, DataFrame)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_insider_trade_list, code, None, num, None)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"内部人交易获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records")
            clean = [
                {
                    "name": r.get("name"),
                    "title": r.get("title"),
                    "transaction_type": r.get("transaction_type"),
                    "trade_shares": safe_float(r.get("trade_shares")),
                    "min_trade_date_str": r.get("min_trade_date_str"),
                    "max_trade_date_str": r.get("max_trade_date_str"),
                    "min_price": safe_float(r.get("min_price")),
                    "max_price": safe_float(r.get("max_price")),
                    "security_description": r.get("security_description"),
                    "source_group_name": r.get("source_group_name"),
                    "holder_id": r.get("holder_id"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_insider_trade_list 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P1.6: 分红 / 回购 / 拆股（公司行动）────────────────────────────
    @with_global_retry
    async def get_corporate_actions_dividends(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """分红记录（派息历史）。

        futu `get_corporate_actions_dividends(code)` → (ret, dict)，dict 含 dividend_list。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_corporate_actions_dividends, code)
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"分红记录获取失败: {data}",
                    "code": code,
                }
            rows = data.get("dividend_list", []) or []
            clean = [
                {
                    "pub_date": r.get("pub_date"),
                    "record_date": r.get("record_date"),
                    "ex_date": r.get("ex_date"),
                    "dividend_payable_date": r.get("dividend_payable_date"),
                    "statement": r.get("statement"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_corporate_actions_dividends 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_corporate_actions_buybacks(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """回购记录（仅支持港股/A股正股和基金）。

        futu `get_corporate_actions_buybacks(code, next_key, num)` → (ret, dict)，
        dict 含 hk_buy_back_list(港股) / a_buy_back_list(A股)。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_corporate_actions_buybacks, code, None, num)
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"回购记录获取失败: {data}",
                    "code": code,
                }
            # hk_buy_back_list / a_buy_back_list 为 DataFrame
            rows = []
            for key in ("hk_buy_back_list", "a_buy_back_list"):
                df = data.get(key)
                if isinstance(df, pd.DataFrame) and not df.empty:
                    for _, r in df.iterrows():
                        rows.append(
                            {
                                "market": "HK" if key.startswith("hk") else "A",
                                "publ_date_str": r.get("publ_date_str") or r.get("change_reg_date_str"),
                                "buy_back_money": safe_float(r.get("buy_back_money")),
                                "buy_back_sum": safe_float(r.get("buy_back_sum")),
                                "percentage": safe_float(r.get("percentage")),
                                "cumulative_percentage": safe_float(r.get("cumulative_percentage")),
                                "high_price": safe_float(r.get("high_price")),
                                "low_price": safe_float(r.get("low_price")),
                                "share_type": r.get("share_type"),
                            }
                        )
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(rows),
                "data": rows,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_corporate_actions_buybacks 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    @with_global_retry
    async def get_corporate_actions_stock_splits(
        self,
        ticker: str,
        num: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """拆股记录（拆合股历史）。

        futu `get_corporate_actions_stock_splits(code, next_key, num)` → (ret, dict)，dict 含 split_list。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }

        try:
            ret, data = await asyncio.to_thread(ctx.get_corporate_actions_stock_splits, code, None, num)
            if ret != RET_OK or not isinstance(data, dict):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"拆股记录获取失败: {data}",
                    "code": code,
                }
            rows = data.get("split_list", []) or []
            clean = [
                {
                    "dir_deci_pub_date_str": r.get("dir_deci_pub_date_str"),
                    "reform_type": r.get("reform_type"),
                    "rate": r.get("rate"),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_corporate_actions_stock_splits 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}

    # ── P0.5.4: 0DTE 末日期权筛选器（市场级）────────────────────────────────
    @with_global_retry
    async def get_option_zero_dte_screener(
        self,
        market: str = "US_SECURITY",
        sort_type: Optional[str] = None,
        is_asc: Optional[bool] = None,
        count: int = 20,
        page: int = 1,
        filter_list: Optional[Any] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.4 0DTE 末日期权筛选器（市场级列表）。

        get_option_zero_dte_screener(market, sort_type, is_asc, count, page, filter_list)
        → (ret, dict)。实测 dict 含 item_list(owner/chain_info 嵌套)/next_page/update_timestamp。
        market 有效值: US_SECURITY/HK_SECURITY/US_INDEX/HK_INDEX。
        """
        from futu import OptionMarket

        mkt = getattr(OptionMarket, str(market).upper(), OptionMarket.US_SECURITY)
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}
        try:
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_zero_dte_screener,
                mkt,
                sort_type,
                is_asc,
                int(count),
                int(page),
                filter_list,
            )
            if ret != RET_OK or not isinstance(data, dict):
                return {"status": "error", "source": "futu", "message": f"0DTE 筛选器获取失败: {data}"}
            item_list = data.get("item_list")
            items = []
            if isinstance(item_list, pd.DataFrame) and not item_list.empty:
                for _, r in item_list.iterrows():
                    items.append(
                        {
                            "owner": r.get("owner"),
                            "chain_info": r.get("chain_info"),
                        }
                    )
            return {
                "status": "success",
                "source": "futu",
                "market": str(market).upper(),
                "count": len(items),
                "next_page": data.get("next_page"),
                "update_timestamp": data.get("update_timestamp"),
                "data": items,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_zero_dte_screener 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── P0.5.4: 0DTE 合约明细（需 chain_info）────────────────────────────────
    @with_global_retry
    async def get_option_zero_dte_contract(
        self,
        owner: str,
        chain_info: Any,
        strike_date_timestamp: Optional[int] = None,
        sort_type: Optional[str] = None,
        is_asc: Optional[bool] = None,
        filter_list: Optional[Any] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.4 0DTE 合约明细（从 zero_dte_screener 的 item.chain_info 取入参）。

        get_option_zero_dte_contract(owner, strike_date_timestamp, chain_info, sort_type, is_asc, filter_list)
        → (ret, DataFrame)。实测列: option/name/option_type/option_price/iv/delta/gamma/vega/theta/
        buy_break_even_point/buy_profit_probability/sell_profit_probability。
        """
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}
        try:
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_zero_dte_contract,
                owner,
                strike_date_timestamp,
                chain_info,
                sort_type,
                is_asc,
                filter_list,
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"0DTE 合约获取失败: {data}"}
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [
                {
                    "option": r.get("option"),
                    "name": r.get("name"),
                    "option_type": r.get("option_type"),
                    "option_price": safe_float(r.get("option_price")),
                    "iv": safe_float(r.get("iv")),
                    "delta": safe_float(r.get("delta")),
                    "buy_break_even_point": safe_float(r.get("buy_break_even_point")),
                    "buy_profit_probability": safe_float(r.get("buy_profit_probability")),
                    "sell_profit_probability": safe_float(r.get("sell_profit_probability")),
                }
                for r in rows
            ]
            return {"status": "success", "source": "futu", "owner": owner, "count": len(clean), "data": clean}
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_zero_dte_contract 失败 %s: %s", owner, e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── P0.5.5: 财报期权筛选器（市场级）─────────────────────────────────────
    @with_global_retry
    async def get_option_earnings_screener(
        self,
        market: str = "US_SECURITY",
        sort_type: Optional[str] = None,
        is_asc: Optional[bool] = None,
        count: int = 20,
        page: int = 1,
        filter_list: Optional[Any] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.5 财报期权筛选器（财报公布标的期权数据）。

        get_option_earnings_screener(market, sort_type, is_asc, count, page, filter_list)
        → (ret, dict)。实测 dict 含 item_list(owner/name/estimate_revenue_yoy/expected_move_ratio)/next_page/all_count。
        """
        from futu import OptionMarket

        mkt = getattr(OptionMarket, str(market).upper(), OptionMarket.US_SECURITY)
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}
        try:
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_earnings_screener,
                mkt,
                sort_type,
                is_asc,
                int(count),
                int(page),
                filter_list,
            )
            if ret != RET_OK or not isinstance(data, dict):
                return {"status": "error", "source": "futu", "message": f"财报期权筛选器获取失败: {data}"}
            item_list = data.get("item_list")
            items = []
            if isinstance(item_list, pd.DataFrame) and not item_list.empty:
                for _, r in item_list.iterrows():
                    items.append(
                        {
                            "owner": r.get("owner"),
                            "name": r.get("name"),
                            "estimate_revenue_yoy": safe_float(r.get("estimate_revenue_yoy")),
                            "expected_move_ratio": safe_float(r.get("expected_move_ratio")),
                        }
                    )
            return {
                "status": "success",
                "source": "futu",
                "market": str(market).upper(),
                "count": len(items),
                "next_page": data.get("next_page"),
                "all_count": data.get("all_count"),
                "data": items,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_earnings_screener 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── P0.5.6: 卖方策略筛选器（市场级，备兑看涨/现金担保卖沽）───────────────
    @with_global_retry
    async def get_option_seller_screener(
        self,
        market: str = "US_SECURITY",
        seller_type: str = "COVERED_CALL",
        sort_type: Optional[str] = None,
        is_asc: Optional[bool] = None,
        filter_list: Optional[Any] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.6 卖方策略筛选器（备兑看涨 COVERED_CALL / 现金担保卖沽 CASH_SECURED_PUT）。

        get_option_seller_screener(market, seller_type, sort_type, is_asc, filter_list)
        → (ret, DataFrame)。实测列: option/name/premium/otm_degree/iv/interval_return/
        annualized_return/itm_probability/owner。
        """
        from futu import OptionMarket, SellerType

        mkt = getattr(OptionMarket, str(market).upper(), OptionMarket.US_SECURITY)
        st = getattr(SellerType, str(seller_type).upper(), SellerType.COVERED_CALL)
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "message": "Futu OpenD 未连接"}
        if self.conn_mgr.status != "CONNECTED":
            return {"status": "error", "source": "futu", "message": "Futu OpenD 重连中，请稍后重试"}
        try:
            ret, data = await asyncio.to_thread(
                self.conn_mgr.quote_ctx.get_option_seller_screener, mkt, st, sort_type, is_asc, filter_list
            )
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {"status": "error", "source": "futu", "message": f"卖方策略筛选器获取失败: {data}"}
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [
                {
                    "option": r.get("option"),
                    "name": r.get("name"),
                    "option_type": r.get("option_type"),
                    "owner": r.get("owner"),
                    "strike_price": safe_float(r.get("strike_price")),
                    "premium": safe_float(r.get("premium")),
                    "otm_degree": safe_float(r.get("otm_degree")),
                    "iv": safe_float(r.get("iv")),
                    "interval_return": safe_float(r.get("interval_return")),
                    "annualized_return": safe_float(r.get("annualized_return")),
                    "itm_probability": safe_float(r.get("itm_probability")),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "market": str(market).upper(),
                "seller_type": str(seller_type).upper(),
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_seller_screener 失败: %s", e)
            return {"status": "error", "source": "futu", "message": str(e)}

    # ── P0.5.7: 行权概率（期权合约代码）─────────────────────────────────────
    @with_global_retry
    async def get_option_exercise_probability(
        self,
        ticker: str,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """P0.5.7 行权概率（入参须为期权合约代码）。

        get_option_exercise_probability(code) → (ret, DataFrame)。
        实测列: timestamp/timestamp_str/security_price/strike_probability。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "富途原生不支持该大类资产"}
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "标的代码格式无法识别"}
        if self.conn_mgr.quote_ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}
        if self.conn_mgr.status != "CONNECTED":
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 重连中，请稍后重试",
                "code": code,
            }
        try:
            ret, data = await asyncio.to_thread(self.conn_mgr.quote_ctx.get_option_exercise_probability, code)
            if ret != RET_OK or not isinstance(data, pd.DataFrame):
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"行权概率获取失败: {data}",
                    "code": code,
                }
            rows = data.to_dict("records") if hasattr(data, "to_dict") else list(data)
            clean = [
                {
                    "date_str": r.get("timestamp_str"),
                    "security_price": safe_float(r.get("security_price")),
                    "strike_probability": safe_float(r.get("strike_probability")),
                }
                for r in rows
            ]
            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_option_exercise_probability 失败 %s: %s", code, e)
            return {"status": "error", "source": "futu", "ticker": ticker, "message": str(e), "code": code}
