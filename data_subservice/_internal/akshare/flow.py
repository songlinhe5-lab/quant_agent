"""AKShare 资金流向（沪深港通 / 港股通双通道 / 十大持股）。

物理解耦，零 backend 依赖，相对 import。
底层拉取 + 解析逻辑完整下沉自 backend.services.akshare.flow，
保证返回结构与主服务历史契约一致。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import akshare as ak

from data_subservice._internal.logger import logger
from data_subservice._internal.retry_utils import with_global_retry


def _to_float(v: Any) -> float:
    try:
        if v is None or v == "" or v == "None":
            return 0.0
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0


def _to_int(v: Any) -> int:
    try:
        if v is None or v == "" or v == "None":
            return 0
        return int(float(str(v).replace(",", "")))
    except (ValueError, TypeError):
        return 0


def get_northbound_flow() -> Optional[Dict]:
    """获取北向资金净流入（轻量结构，供 FUND_FLOW action 使用）。"""
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        return {
            "date": str(latest.get("日期")),
            "northbound_net_inflow": float(latest.get("北向资金") or 0),
            "source": "akshare",
        }
    except Exception as e:
        logger.error(f"[AKShare] 北向资金失败: {e}")
        return None


@with_global_retry
def get_southbound_flow() -> Dict[str, Any]:
    """南向资金当日累计净买入 + 近30日趋势（对齐主服务 get_southbound_flow 返回结构）。"""
    try:
        summary = ak.stock_hsgt_fund_flow_summary_em()
        hist = ak.stock_hsgt_hist_em(symbol="南向资金")
        if summary is None or summary.empty:
            raise ValueError("获取到的资金流向汇总数据异常")
        south_df = summary[summary["资金方向"] == "南向"]
        if south_df.empty:
            raise ValueError("未在数据中找到南向资金方向的明细")
        net_inflow = float(south_df["资金净流入"].sum())
        date_str = str(south_df["交易日"].iloc[0])

        sparkline = [1, 1, -1, 1, 1, 1, -1, 1]
        weekly = monthly = history = None
        if hist is not None and not hist.empty:
            target_col = "当日成交净买额" if "当日成交净买额" in hist.columns else "当日资金流入"
            if target_col in hist.columns:
                series = hist[target_col].astype(float)
                sparkline = [round(float(v), 2) for v in series.tail(8).tolist()]
                weekly = round(float(series.tail(5).sum()), 2)
                monthly = round(float(series.tail(22).sum()), 2)
                history = [round(float(v), 2) for v in series.tail(30).tolist()]
                if net_inflow >= 800.0 and len(sparkline) > 0:
                    net_inflow = float(sparkline[-1])
        if net_inflow >= 800.0:
            raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")
        is_closed = int(south_df["交易状态"].iloc[0]) == 3 if "交易状态" in south_df.columns else False
        return {
            "status": "success",
            "data": {
                "net_inflow": round(net_inflow, 2),
                "weekly": weekly,
                "monthly": monthly,
                "unit": "亿人民币",
                "date": date_str,
                "sparkline": sparkline,
                "history": history,
            },
            "is_closed": is_closed,
            "source": "akshare_stock_hsgt_fund_flow_summary",
        }
    except Exception as e:
        logger.error(f"[AKShare] 南向资金失败: {e}")
        return {
            "status": "warning",
            "message": "南向资金数据获取失败，暂无可用数据",
            "data": None,
            "source": "akshare-unavailable",
        }


@with_global_retry
def get_northbound_flow_full() -> Dict[str, Any]:
    """北向资金完整结构（对齐主服务 get_northbound_flow 返回结构）。"""
    try:
        summary = ak.stock_hsgt_fund_flow_summary_em()
        hist = ak.stock_hsgt_hist_em(symbol="北向资金")
        if summary is None or summary.empty:
            raise ValueError("获取到的资金流向汇总数据异常")
        north_df = summary[summary["资金方向"] == "北向"]
        if north_df.empty:
            raise ValueError("未在数据中找到北向资金方向的明细")
        net_inflow = float(north_df["资金净流入"].sum())
        date_str = str(north_df["交易日"].iloc[0])

        sparkline = [-1, -1, 1, -1, -1, 1, -1, -1]
        weekly = monthly = history = None
        if hist is not None and not hist.empty:
            target_col = "当日成交净买额" if "当日成交净买额" in hist.columns else "当日资金流入"
            if target_col in hist.columns:
                series = hist[target_col].astype(float)
                sparkline = [round(float(v), 2) for v in series.tail(8).tolist()]
                weekly = round(float(series.tail(5).sum()), 2)
                monthly = round(float(series.tail(22).sum()), 2)
                history = [round(float(v), 2) for v in series.tail(30).tolist()]
                if net_inflow >= 1000.0 and len(sparkline) > 0:
                    net_inflow = float(sparkline[-1])
        if net_inflow >= 1000.0:
            raise ValueError("AKShare 返回了总额度而非净流入，且无法用历史数据拯救，判定为接口异常")
        is_closed = int(north_df["交易状态"].iloc[0]) == 3 if "交易状态" in north_df.columns else False
        return {
            "status": "success",
            "data": {
                "net_inflow": round(net_inflow, 2),
                "weekly": weekly,
                "monthly": monthly,
                "unit": "亿人民币",
                "date": date_str,
                "sparkline": sparkline,
                "history": history,
            },
            "is_closed": is_closed,
            "source": "akshare_stock_hsgt_fund_flow_summary",
        }
    except Exception as e:
        logger.error(f"[AKShare] 北向资金失败: {e}")
        return {
            "status": "warning",
            "message": "北向资金数据获取失败，暂无可用数据",
            "data": None,
            "source": "akshare-unavailable",
        }


@with_global_retry
def get_hk_connect_flow() -> Dict[str, Any]:
    """港股通(南向)双通道资金流向明细（对齐主服务 get_hk_stock_connect_flow）。"""
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        if df is None or df.empty:
            raise ValueError("获取到的港股通资金流向汇总数据异常")
        south_df = df[df["资金方向"] == "南向"].copy()
        if south_df.empty:
            raise ValueError("未在数据中找到南向(港股通)资金明细")
        channels = []
        total_net_buy = 0.0
        for _, row in south_df.iterrows():
            net_buy = _to_float(row.get("成交净买额"))
            total_net_buy += net_buy
            channels.append(
                {
                    "board": str(row.get("板块", "")),
                    "net_buy": round(net_buy, 2),
                    "net_inflow": round(_to_float(row.get("资金净流入")), 2),
                    "up": _to_int(row.get("上涨数")),
                    "down": _to_int(row.get("下跌数")),
                    "flat": _to_int(row.get("持平数")),
                    "index": str(row.get("相关指数", "")),
                    "index_chg": round(_to_float(row.get("指数涨跌幅")), 2),
                }
            )
        date_str = str(south_df["交易日"].iloc[0])
        return {
            "status": "success",
            "data": {
                "trade_date": date_str,
                "total_net_buy": round(total_net_buy, 2),
                "unit": "亿元",
                "channels": channels,
            },
            "source": "akshare_stock_hsgt_fund_flow_summary",
        }
    except Exception as e:
        logger.error(f"[AKShare] 港股通资金流向失败: {e}")
        return {
            "status": "warning",
            "message": "港股通资金流向获取失败，暂无可用数据",
            "data": None,
            "source": "akshare-unavailable",
        }


@with_global_retry
def get_hsgt_top_holders(symbol: str = "00700") -> Dict[str, Any]:
    """沪深港通个股持仓明细（对齐主服务 get_hsgt_top_holders）。"""
    try:
        today = datetime.now()
        end_date = today.strftime("%Y%m%d")
        start_date = (today - timedelta(days=20)).strftime("%Y%m%d")
        df = ak.stock_hsgt_individual_detail_em(symbol=symbol, start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            raise ValueError(f"沪深港通持股明细数据为空 ({symbol})")

        dates = sorted(df["持股日期"].unique(), reverse=True)
        latest_date = dates[0]
        prev_date = dates[1] if len(dates) > 1 else None
        latest_df = df[df["持股日期"] == latest_date]
        prev_df = df[df["持股日期"] == prev_date] if prev_date else None

        prev_map = (
            {str(row.get("机构名称", "")): float(row.get("持股数量", 0) or 0) for _, row in prev_df.iterrows()}
            if prev_df is not None and not prev_df.empty
            else {}
        )
        if "持股数量" in latest_df.columns:
            latest_df = latest_df.sort_values(by="持股数量", ascending=False)

        southbound_total = float(latest_df["持股数量"].sum())
        prev_southbound_total = (
            float(prev_df["持股数量"].sum()) if prev_df is not None and not prev_df.empty else southbound_total
        )
        total_net_change = southbound_total - prev_southbound_total

        participants_summary = []
        for _, row in latest_df.head(20).iterrows():
            holder = str(row.get("机构名称", ""))
            shares = float(row.get("持股数量", 0) or 0)
            pct = float(row.get("持股数量占A股百分比", row.get("占已发行股份百分比", 0)) or 0)
            prev_shares = prev_map.get(holder, shares)
            net_change = shares - prev_shares
            participants_summary.append(
                {
                    "holder": holder,
                    "shares": round(shares, 0),
                    "net_change": round(net_change, 0),
                    "pct": round(pct, 2),
                    "is_southbound": True,
                }
            )
        return {
            "status": "success",
            "data": {
                "symbol": symbol,
                "date": str(latest_date),
                "southbound_total_shares": round(southbound_total, 0),
                "southbound_net_change": round(total_net_change, 0),
                "participants": participants_summary,
                "total_shares_sampled": round(southbound_total, 0),
            },
            "source": "akshare_stock_hsgt_individual_detail",
        }
    except Exception as e:
        logger.error(f"[AKShare] CCASS {symbol} 失败: {e}")
        return {
            "status": "warning" if isinstance(e, ValueError) else "error",
            "message": str(e),
            "data": None,
        }


def get_individual_flow(symbol: str) -> Optional[Dict]:
    """获取个股资金流向。"""
    try:
        df = ak.stock_individual_fund_flow(stock=symbol, market="sh")
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        return {
            "symbol": symbol,
            "main_net_inflow": float(latest.get("主力净流入-净额") or 0),
            "date": str(latest.get("日期")),
            "source": "akshare",
        }
    except Exception as e:
        logger.error(f"[AKShare] 个股资金流 {symbol} 失败: {e}")
        return None
