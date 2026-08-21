"""
Futu 期权与资金流处理模块
负责期权链、资金流向、基本面数据等功能
"""

import asyncio
import logging
import time
from typing import Any, Dict

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

        result = {
            "status": "success",
            "data": {
                "ticker": ticker,
                "company_name": str(row.get("name", "")),
                "trailing_PE": safe_float(row.get("pe_ratio", 0.0))
                if safe_float(row.get("pe_ratio", 0.0)) > 0
                else None,  # noqa: E501
                "price_to_book": safe_float(row.get("pb_rate", 0.0))
                if safe_float(row.get("pb_rate", 0.0)) > 0
                else None,  # noqa: E501
                "dividend_yield": f"{safe_float(row.get('dividend_yield', 0.0))}%"
                if safe_float(row.get("dividend_yield", 0.0)) > 0
                else None,  # noqa: E501
                "market_cap": safe_float(row.get("market_val", 0.0))
                if safe_float(row.get("market_val", 0.0)) > 0
                else None,  # noqa: E501
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
    # 富途返回 field_id 是英文枚举（如 CASH_EQUIVALENTS），前端/用户需中文字段名。
    # 这里建映射表，缺失的 field_id 保留原值透传（零幻觉：不臆造中文名）。
    FINANCIAL_FIELD_MAP = {
        # 资产负债表
        "CASH_EQUIVALENTS": "现金及现金等价物",
        "SHORT_TERM_INVESTMENT": "短期投资",
        "TRADE_RECEIVABLE": "应收账款",
        "INVENTORY": "存货",
        "TOTAL_CURRENT_ASSETS": "流动资产合计",
        "TOTAL_ASSETS": "资产总计",
        "TRADE_PAYABLE": "应付账款",
        "TOTAL_CURRENT_LIABILITIES": "流动负债合计",
        "TOTAL_LIABILITIES": "负债合计",
        "TOTAL_EQUITY": "所有者权益合计",
        "RETAINED_EARNINGS": "留存收益",
        # 利润表
        "TOTAL_OPERATING_REVENUE": "营业总收入",
        "TOTAL_OPERATING_COST": "营业总成本",
        "GROSS_PROFIT": "毛利",
        "OPERATING_PROFIT": "营业利润",
        "NET_PROFIT": "净利润",
        "BASIC_EPS": "基本每股收益",
        "DILUTED_EPS": "稀释每股收益",
        # 现金流量表
        "NET_CASH_FLOW_FROM_OPERATING": "经营活动净现金流",
        "NET_CASH_FLOW_FROM_INVESTING": "投资活动净现金流",
        "NET_CASH_FLOW_FROM_FINANCING": "筹资活动净现金流",
        "FREE_CASH_FLOW": "自由现金流",
    }

    async def get_financials_statements(
        self,
        ticker,
        statement_type=None,
        financial_type=None,
        currency_code=None,
        num=1,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取三大财务报表（资产负债表/利润表/现金流量表）。

        入参:
          statement_type: "BALANCE_SHEET" | "INCOME_STATEMENT" | "CASH_FLOW"（None 取默认）
          financial_type: "ANNUAL" | "INTERIM" | "QUARTER"（None 取默认）
          currency_code:  "HKD" | "USD" | ...（None 取原始货币）
          num:            返回期数（默认 1，即最近一期）
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

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {"status": "error", "source": "futu", "ticker": ticker, "message": "Futu OpenD 未连接", "code": code}

        try:
            # 10.10: get_financials_statements(code, statement_type, financial_type,
            #        currency_code, next_key, num) — 收字符串/None，非枚举类
            ret, data = ctx.get_financials_statements(
                code,
                statement_type=statement_type,
                financial_type=financial_type,
                currency_code=currency_code,
                num=num,
            )
            if ret != RET_OK:
                return {"status": "error", "source": "futu", "ticker": ticker, "message": str(data), "code": code}

            # 防护：10.10 下 data 可能为 str（错误消息）而非 DataFrame/Iterable，直接 to_dict/list 会抛 'str' 异常
            if isinstance(data, str):
                return {"status": "error", "source": "futu", "ticker": ticker, "message": data, "code": code}

            # 字段级映射：field_id -> 中文
            if hasattr(data, "to_dict"):
                rows = data.to_dict("records")
            else:
                rows = list(data)
            mapped = []
            for r in rows:
                field_id = r.get("field_id")
                r = dict(r)
                r["field_name_cn"] = self.FINANCIAL_FIELD_MAP.get(field_id, field_id)
                mapped.append(r)

            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "statement_type": statement_type,
                "financial_type": financial_type,
                "count": len(mapped),
                "data": mapped,
            }
        except Exception as e:
            logger.error(f"❌ get_financials_statements 失败 {code}: {e}")
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
