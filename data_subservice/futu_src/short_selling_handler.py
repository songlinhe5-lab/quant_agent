# -*- coding: utf-8 -*-
"""F1 · 卖空数据分析 handler（港股/美股卖空榜 + 每日卖空量）。

接口源自 Futu OpenD 10.10.7008（经本机 Mac OpenD 实测验证，详见
docs/TODO-FUTU-INTERFACE-CAPABILITY.md F1 段与 memory 实测结论）：

- ``get_short_selling_rank(market=, count=)`` → ``(ret, data)`` 二元组；
  ``ret==RET_OK`` 时 ``data`` 为 ``(all_count, DataFrame)`` 二元组
  （注意并非直接 DataFrame），列含 ``security / name / close_price /
  change_ratio / volume / short_sell_volume / short_sell_ratio / ...``，
  反映当日卖空成交活跃度榜。
- ``get_daily_short_volume(code=)`` → ``(ret_code, us_df, hk_df)`` 三元组。
  ⚠️ 港美股**分表**：港股数据在 ``[2]``、美股在 ``[1]``（不是 (ret, data, next_key)，
  历史注释与实现均据此写错，导致港股恒 no_data，2026-08-30 修复）。
  美股列含 ``short_percent / total_shares_short / volume / close_price / ...``；
  港股列含 ``short_sell_turnover / turnover / short_sell_shares_traded /
  shares_traded / ...``——**港股表无 short_percent**，占比须自行计算。
  **T-1 语义**：盘后结算，最新可得通常为前一交易日；但空返回必须如实标
  ``no_data`` 而非 0，禁止臆造卖空量为 0（零幻觉红线）。

约定（与 option_fund_handler 一致）：
- ``format_ticker_func``：ticker → futu 代码（如 ``HK.00700``），缺失时回退原 ticker
- ``is_unsupported_func``：标的非港股/美股/沪深时返回 error
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from futu import RET_OK

from ._compat import safe_float

logger = logging.getLogger(__name__)


def _market_from_code(code: str):
    """从 futu 代码前缀推导 Market 枚举（HK/US/CN），其他返回 None。"""
    from futu import Market

    if code.startswith("HK."):
        return Market.HK
    if code.startswith("US."):
        return Market.US
    if code.startswith(("SH.", "SZ.")):
        return Market.CN
    return None


class ShortSellingHandler:
    """卖空数据 handler（依赖 OpenD 连接管理器）。"""

    def __init__(self, conn_mgr):
        self.conn_mgr = conn_mgr

    # ── F1-1: 卖空榜（当日卖空成交活跃度）──────────────────────────────
    async def get_short_selling_rank(
        self,
        ticker: str,
        market: Optional[str] = None,
        count: int = 10,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取卖空成交榜（按成交额/成交量排序的当日卖空头寸活跃度）。"""
        if ticker and is_unsupported_func and is_unsupported_func(ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "标的非港股/美股/沪深，富途不支持卖空数据",
            }
        code = format_ticker_func(ticker) if format_ticker_func else ticker

        # market 优先用显式参数，否则从代码前缀推导（卖空榜为市场级接口，
        # ticker 可选——纯市场模式 market=已给时无需 code，仅当两者皆缺才报错）
        mkt = None
        if market:
            from futu import Market

            mkt = getattr(Market, market.upper(), None)
        if mkt is None and code:
            mkt = _market_from_code(code)

        if mkt is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "未提供标的代码且无法推导卖空榜市场",
                "code": code,
            }

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": code,
            }

        try:
            # 签名: (ret, data)；ret==RET_OK 时 data 为 (all_count, DataFrame) 二元组
            res = ctx.get_short_selling_rank(market=mkt, count=count)
            if not isinstance(res, (list, tuple)) or len(res) < 2:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"卖空榜接口返回形态异常: {type(res)}",
                    "code": code,
                }
            ret, data = res[0], res[1]
            if ret != RET_OK:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": str(data),
                    "code": code,
                }

            # ret==RET_OK 时 data = (all_count, DataFrame)
            if isinstance(data, (list, tuple)) and len(data) == 2 and hasattr(data[1], "to_dict"):
                df = data[1]
            elif hasattr(data, "to_dict"):
                df = data
            else:
                df = data

            if hasattr(df, "to_dict"):
                rows = df.to_dict("records")
            else:
                rows = list(df)

            # 数值安全化（缺失保留原值，不臆造）
            clean = []
            for r in rows:
                rec = {k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()}
                clean.append(rec)

            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "market": str(mkt).split(".")[-1],
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_short_selling_rank 失败 %s: %s", code, e)
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": str(e),
                "code": code,
            }

    # ── F1-2: 每日卖空量（T-1 结算语义）──────────────────────────────
    async def get_daily_short_volume(
        self,
        ticker: str,
        date: Optional[str] = None,
        format_ticker_func=None,
        is_unsupported_func=None,
    ) -> Dict[str, Any]:
        """获取每日卖空量（港股/美股 T-1 结算，当日盘后通常为 0 行）。

        零幻觉红线：空返回如实标 ``no_data``，严禁将缺失卖空量填为 0。
        """
        if is_unsupported_func and is_unsupported_func(ticker):
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "标的非港股/美股/沪深，富途不支持卖空数据",
            }
        code = format_ticker_func(ticker) if format_ticker_func else ticker
        if not code:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "标的代码格式无法识别",
            }

        ctx = self.conn_mgr.get_quote_ctx()
        if ctx is None:
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": "Futu OpenD 未连接",
                "code": code,
            }

        try:
            # ⚠️ 真实签名是 (ret_code, us_df, hk_df) 三元组，不是 (ret, data, next_key)。
            # 港股数据在 [2]、美股在 [1]；旧实现恒取 res[1]（美股表）→ 港股查询永远
            # 拿到空表 → 恒 no_data。2026-08-30 实测：US.AAPL 返回 10 行真实数据，
            # HK.00700 恒 0 行——后者并非 T-1 无数据，而是取错了表。
            res = ctx.get_daily_short_volume(code=code)
            if not isinstance(res, (list, tuple)) or len(res) < 3:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": f"卖空量接口返回形态异常: {type(res)}",
                    "code": code,
                }
            ret, us_df, hk_df = res[0], res[1], res[2]
            if ret != RET_OK:
                return {
                    "status": "error",
                    "source": "futu",
                    "ticker": ticker,
                    "message": str(us_df),
                    "code": code,
                }

            # 按标的市场选表：港股 hk_df / 其它 us_df；目标表为空时回退另一张表
            from futu import Market

            hk_first = _market_from_code(code) == Market.HK
            primary, fallback = (hk_df, us_df) if hk_first else (us_df, hk_df)
            data = primary if (primary is not None and len(primary) > 0) else fallback

            if hasattr(data, "to_dict"):
                rows = data.to_dict("records")
            else:
                rows = list(data)

            # T-1 语义：当日盘后 0 行属正常，如实标注 no_data
            if not rows:
                return {
                    "status": "no_data",
                    "source": "futu",
                    "ticker": ticker,
                    "code": code,
                    "message": "当日卖空量尚未结算（T-1 语义，盘后查询为 0 行）",
                    "count": 0,
                    "data": [],
                }

            clean = []
            for r in rows:
                rec = {k: safe_float(v) if isinstance(v, (int, float)) else v for k, v in r.items()}
                clean.append(rec)

            return {
                "status": "success",
                "source": "futu",
                "ticker": ticker,
                "code": code,
                "count": len(clean),
                "data": clean,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("❌ get_daily_short_volume 失败 %s: %s", code, e)
            return {
                "status": "error",
                "source": "futu",
                "ticker": ticker,
                "message": str(e),
                "code": code,
            }
