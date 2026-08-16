"""
宏观领域业务适配器（BE-ARCH-06b）

在 DataServiceFacade 之上，提供面向「宏观」语义的封装：get_macro_series /
get_economic_calendar。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from backend.services.datasource.business.facade import DataServiceFacade, data_service


class MacroDataService:
    """宏观领域业务适配器。"""

    def __init__(self, facade: DataServiceFacade | None = None) -> None:
        self._facade = facade or data_service

    async def get_macro_series(
        self, series_id: str, limit: int = 100, prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """宏观经济序列（FRED 等）。"""
        if not series_id or not str(series_id).strip():
            raise ValueError("series_id 不能为空")
        return await self._facade.get_macro_series(series_id, limit=limit, prefer_sources=prefer_sources)

    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """宏观经济日历（fred / dbnomics / rbi 多源融合 + CPI actual 回填）。"""
        return await self._facade.get_economic_calendar(
            days_ahead=days_ahead, days_back=days_back, prefer_sources=prefer_sources
        )

    async def get_company_news(
        self, ticker: str, days_back: int = 3, prefer_sources: Optional[list[str]] = None
    ) -> Any:
        """个股新闻（宏观视角下的事件驱动数据）。"""
        return await self._facade.get_company_news(ticker, days_back=days_back, prefer_sources=prefer_sources)

    # ── F4-2: FedWatch FOMC 隐含概率（Tier1 宏观前瞻，支撑 G5）──────────
    async def get_fed_watch(self, prefer_sources: Optional[list[str]] = None) -> Any:
        """FedWatch FOMC 目标利率隐含概率（市场级，无 code 参数）。"""
        return await self._facade._dispatch(
            "FED_WATCH",
            {},
            prefer_sources=prefer_sources or ["futu"],
            enable_merge=False,
        )

    async def get_fed_watch_panel(self, prefer_sources: Optional[list[str]] = None) -> Any:
        """G5：FedWatch 面板（产品级聚合）。

        在 get_fed_watch 原始数据之上做防御式派生：
          - 自动识别会议日期列与利率区间概率列（Futu 列名随版本变动，不硬编码）
          - 提取下一会议（最早未来日期）"最概率利率区间"隐含中点
          - 计算政策斜率 policy_slope：下一会议隐含利率 vs 其后会议，判定 hawkish/dovish/flat
        原始 data 原样保留，panel 仅做增强；解析失败给 note 而非崩溃（零幻觉红线）。
        """
        res = await self.get_fed_watch(prefer_sources=prefer_sources)
        if res.is_error:
            return res

        data = res.data
        if not isinstance(data, dict):
            return res

        df = data.get("df")
        if df is None or not isinstance(df, list) or len(df) == 0:
            data["panel"] = {"available": False, "note": "FedWatch 原始数据为空，无法合成面板"}
            return res

        rows = df
        # 1) 识别日期列：列名含 date/meeting/时间/会议
        date_col = next(
            (k for k in rows[0].keys() if any(t in str(k).lower() for t in ("date", "meeting", "时间", "会议"))),
            None,
        )
        # 2) 识别利率区间列：列名含 % 或 -，且非日期类
        rate_cols = [
            k
            for k in rows[0].keys()
            if any(t in str(k) for t in ("%", "-"))
            and "date" not in str(k).lower()
            and "meeting" not in str(k).lower()
            and "时间" not in str(k)
        ]

        def _mid_of_bucket(name: str) -> Optional[float]:
            nums = re.findall(r"(\d+\.?\d*)", str(name))
            if len(nums) >= 2:
                return round((float(nums[0]) + float(nums[1])) / 2, 4)
            if len(nums) == 1:
                return float(nums[0])
            return None

        def _most_prob_rate(row: dict) -> Optional[float]:
            best, best_col = None, None
            for c in rate_cols:
                try:
                    v = float(row.get(c) or 0)
                except (TypeError, ValueError):
                    continue
                if best is None or v > best:
                    best, best_col = v, c
            return _mid_of_bucket(best_col) if best_col else None

        def _sort_key(r: dict) -> date:
            if date_col and r.get(date_col):
                try:
                    return datetime.strptime(str(r[date_col]), "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    return date(1900, 1, 1)
            return date(1900, 1, 1)

        try:
            sorted_rows = sorted(rows, key=_sort_key)
        except Exception:
            sorted_rows = rows

        meetings = []
        for r in sorted_rows:
            implied = _most_prob_rate(r)
            if implied is not None:
                meetings.append({"date": r.get(date_col) if date_col else None, "implied_rate": implied})

        if len(meetings) >= 1:
            next_meeting = meetings[0]
            policy_slope = "flat"
            slope_bps = None
            if len(meetings) >= 2:
                slope_bps = round((meetings[1]["implied_rate"] - next_meeting["implied_rate"]) * 100, 2)
                if slope_bps > 0.5:
                    policy_slope = "hawkish"  # 后续会议隐含更高利率 → 紧缩
                elif slope_bps < -0.5:
                    policy_slope = "dovish"  # 后续会议隐含更低利率 → 宽松
            data["panel"] = {
                "available": True,
                "next_meeting_date": next_meeting["date"],
                "next_meeting_implied_rate": next_meeting["implied_rate"],
                "policy_slope": policy_slope,
                "slope_bps": slope_bps,
                "meetings": meetings[:6],
            }
        else:
            data["panel"] = {"available": False, "note": "未能从 FedWatch 数据解析出利率区间列"}

        return res


# 领域单例
macro_data_service = MacroDataService()
