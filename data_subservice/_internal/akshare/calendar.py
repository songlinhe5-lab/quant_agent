"""AKShare 宏观日历（复制自 backend.services.akshare.calendar，物理解耦，零 backend 依赖，相对 import）"""

from typing import List

import akshare as ak

from data_subservice._internal.logger import logger


def get_economic_calendar() -> List[dict]:
    """获取宏观经济日历。"""
    try:
        df = ak.macro_china_economic_calendar()
        if df is None or df.empty:
            return []
        return df.head(30).to_dict(orient="records")
    except Exception as e:
        logger.error(f"[AKShare] 宏观日历失败: {e}")
        return []


def get_future_calendar() -> List[dict]:
    """获取期货日历。"""
    try:
        df = ak.futures_rule_summary()
        if df is None or df.empty:
            return []
        return df.head(30).to_dict(orient="records")
    except Exception as e:
        logger.error(f"[AKShare] 期货日历失败: {e}")
        return []
