"""AKShare 资金流向（复制自 backend.services.akshare.flow，物理解耦，零 backend 依赖，相对 import）"""

from typing import Dict, Optional

import akshare as ak

from data_subservice._internal.logger import logger


def get_northbound_flow() -> Optional[Dict]:
    """获取北向资金净流入。"""
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
