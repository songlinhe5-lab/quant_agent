import json
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.core.middleware import httpx_log_request, httpx_log_response
from backend.core.redis_client import redis_client

# ── DBnomics 免费数据源 (聚合 IMF / WorldBank / OECD / ECB 等权威机构, 完全免 Key) ──
_DBNOMICS_BASE = "https://api.db.nomics.world/v22/series"
# OECD G20 CPI 数据集 (消费者价格指数, 全口径, 覆盖 G20 新兴与发达经济体)
_DATASET = "OECD/DSD_G20_PRICES@DF_G20_PRICES"
# 序列后缀: 年度(A) · 国家口径(N) · CPI · 年百分比(PA) · 全口径(_T) · 未做调整(N) · 年增长率(YoY)
_SERIES_SUFFIX = ".A.N.CPI.PA._T.N.GY"

# G20 新兴市场经济体国码 -> 显示名 (AKShare 与 FRED 盲区)
EM_COUNTRIES: Dict[str, str] = {
    "ARG": "Argentina",
    "BRA": "Brazil",
    "CHN": "China",
    "IND": "India",
    "IDN": "Indonesia",
    "MEX": "Mexico",
    "RUS": "Russia",
    "ZAF": "South Africa",
    "TUR": "Türkiye",
}


class DbnomicsService:
    """DBnomics 免费宏观源 (新兴市场 CPI actual 回填, 替代收费 TradingEconomics)

    💡 DBnomics 聚合 IMF / WorldBank / OECD / ECB 等权威机构时序, 完全免 Key。
    此处拉取 OECD G20 CPI 数据集的**年度同比 CPI**, 覆盖印度 / 巴西 / 墨西哥等
    AKShare 与 FRED 缺失的新兴市场, 仅回填 actual 实际值 (非前瞻事件日历)。
    与 RBI (WorldBank 印度 CPI) 形成免费双源, 彻底干掉收费的 TE_API_KEY。
    """

    def __init__(self) -> None:
        self.base_url = _DBNOMICS_BASE

    def _series_ids(self) -> List[str]:
        return [f"{_DATASET}/{code}{_SERIES_SUFFIX}" for code in EM_COUNTRIES]

    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:  # noqa: E501
        """获取 G20 新兴市场 CPI 年度同比最新值, 作为无 Key 新兴市场 actual 回填事件。"""
        cache_key = "quant:macro:dbnomics_cpi"
        if not skip_cache:
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    return {
                        "status": "success",
                        "data": json.loads(cached),
                        "source": "redis_cache",
                    }
            except Exception:
                pass

        # 💡 多序列一次拉取 (observations=true 含 period/value 平行数组)
        params = {"series_ids": ",".join(self._series_ids()), "observations": "true"}
        try:
            async with httpx.AsyncClient(
                timeout=20.0,
                verify=False,
                event_hooks={
                    "request": [httpx_log_request],
                    "response": [httpx_log_response],
                },
            ) as client:
                resp = await client.get(self.base_url, params=params)
                resp.raise_for_status()
                payload = resp.json()

            docs = (payload.get("series") or {}).get("docs") or []
            events: List[Dict[str, Any]] = []
            for doc in docs:
                dims = doc.get("dimensions") or {}
                country_code = dims.get("REF_AREA")
                country = EM_COUNTRIES.get(country_code, country_code)
                if not country:
                    continue
                periods = doc.get("period") or []
                values = doc.get("value") or []
                if not periods or not values or len(periods) != len(values):
                    continue
                # 💡 过滤掉-null 观测, 按索引对齐
                paired = [
                    (str(periods[i]), values[i])
                    for i in range(len(periods))
                    if values[i] is not None
                ]
                if not paired:
                    continue

                latest_period, latest_value = paired[-1]
                prev_value = paired[-2][1] if len(paired) > 1 else None
                # 💡 年度数据用 period_start_day 或年末构造日期
                time_str = self._build_date(latest_period, doc)
                events.append(
                    {
                        "time": time_str,
                        "country": country,
                        "event": f"{country} CPI (YoY)",
                        "impact": "high",
                        "previous": str(prev_value) if prev_value is not None else "",
                        "estimate": "",
                        "actual": str(latest_value),
                        "tz": "UTC",
                    }
                )

            if not events:
                return {
                    "status": "skipped",
                    "message": "DBnomics 暂无可解析的新兴市场 CPI 数据",
                    "data": [],
                }

            try:
                ttl = 86400 * 7 + random.randint(100, 600)
                await redis_client.set(cache_key, json.dumps(events), ex=ttl)
            except Exception:
                pass
            return {"status": "success", "data": events, "source": "dbnomics"}
        except Exception as e:
            return {
                "status": "skipped",
                "message": f"DBnomics 新兴市场 CPI 拉取失败: {e}",
                "data": [],
            }

    @staticmethod
    def _build_date(period: str, doc: Dict[str, Any]) -> str:
        start_days = doc.get("period_start_day") or []
        if start_days and len(start_days) == len(doc.get("period") or []):
            return f"{str(start_days[-1])} 00:00:00"
        # 💡 退化: 仅年份 -> 年末
        try:
            yr = int(period[:4])
            return f"{yr}-12-31 00:00:00"
        except Exception:
            return f"{period}-12-31 00:00:00"


# 全局单例
dbnomics_service = DbnomicsService()
