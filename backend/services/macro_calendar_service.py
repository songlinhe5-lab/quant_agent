"""宏观日历多源聚合器 (全免费白嫖组合)

主源 AKShare(中国+全球前瞻日历) → 新兴市场 actual 回填 DBnomics(OECD G20 CPI, 免 Key)
→ RBI(WorldBank 印度 CPI, 二级兜底) → FRED 权威序列回填 actual(美国核心 + 国际序列)；
全空时 Finnhub(免费档全球) 兜底前瞻日历, 仍空则降级 FRED 发布日历(自带回填)。
已彻底移除收费的 TradingEconomics(TE_API_KEY)。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo

    _ZONEINFO = ZoneInfo
except Exception:  # pragma: no cover
    _ZONEINFO = None  # type: ignore

from backend.app.market_data import market_data
from backend.core.config import settings


class MacroCalendarAggregator:
    """宏观日历聚合核心，封装多源拉取 -> 归一化(UTC) -> 合并去重 -> FRED 回填 -> 兜底。"""

    # 各源发布时间所属时区 (用于归一化为 UTC ISO 发给前端)
    SOURCE_TZ = {
        "akshare": "Asia/Shanghai",
        "finnhub": "UTC",
        "fred": "America/New_York",
        "dbnomics": "UTC",
        "rbi": "UTC",
    }

    async def aggregate(
        self, days_ahead: int = 7, days_back: int = 0, skip_cache: bool = False
    ) -> Dict[str, Any]:
        # 1. 主源: AKShare (中国+全球前瞻日历)
        ak_res = await self._safe(
            market_data.get_economic_calendar_ak(
                days_ahead, days_back=days_back, skip_cache=skip_cache
            )
        )
        normalized: List[Dict[str, Any]] = []
        ak_events = self._extract(ak_res, "akshare")
        if ak_events:
            normalized.extend(ak_events)

        # 2. 新兴市场 actual 回填: DBnomics -> RBI (免费, 无 Key)
        em_res = await self._safe(self._fetch_em(days_ahead, days_back, skip_cache))
        if isinstance(em_res, dict):
            em_events = em_res.get("data", [])
            if isinstance(em_events, list) and em_events:
                normalized.extend(em_events)

        # 3. 去重合并 (优先实际值更完整者)
        merged = self._merge(normalized)

        # 4. FRED 权威序列回填 actual (美国核心 + 国际序列)
        try:
            merged = await market_data.backfill_fred_actuals(merged)
        except Exception as e:
            print(f"⚠️ [MacroAggregator] FRED actual 回填失败: {e}")

        # 5. 全空 -> Finnhub 兜底 (免费档全球前瞻日历)
        if not merged:
            fh_res = await self._safe(
                market_data.get_economic_calendar_finnhub(
                    days_ahead, days_back=days_back, skip_cache=skip_cache
                )
            )
            fh_events = self._extract(fh_res, "finnhub")
            if fh_events:
                merged = fh_events

        # 6. 仍空 -> FRED 发布日历兜底 (自带回填)
        if not merged:
            fred_res = await self._safe(
                market_data.get_economic_calendar_fred(
                    days_ahead, days_back=days_back, skip_cache=skip_cache
                )
            )
            fred_events = self._extract(fred_res, "fred")
            if fred_events:
                merged = fred_events

        contributed = sorted({e.get("_src") for e in merged if e.get("_src")})
        return {
            "status": "success" if merged else "warning",
            "data": merged,
            "sources_contributed": contributed,
            "message": self._build_message(contributed),
        }

    async def _safe(self, coro: Any) -> Any:
        """包裹子源协程，异常时返回 None，绝不拖垮整体聚合。"""
        try:
            return await coro
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ [MacroAggregator] 子源拉取异常: {e}")
            return None

    async def _fetch_em(
        self, days_ahead: int, days_back: int, skip_cache: bool
    ) -> Dict[str, Any]:
        """按 EM_SOURCE_PRIORITY 串联 DBnomics -> RBI (免费, 无 Key 优雅跳过)。"""
        priority = [
            p.strip().lower()
            for p in settings.em_source_priority.split(",")
            if p.strip()
        ]
        out_events: List[Dict[str, Any]] = []
        out_sources: List[str] = []
        for src in priority:
            if src == "dbnomics":
                res = await self._safe(
                    market_data.get_economic_calendar_dbnomics(
                        days_ahead, days_back=days_back, skip_cache=skip_cache
                    )
                )
                events = self._extract(res, "dbnomics")
            elif src == "rbi":
                res = await self._safe(
                    market_data.get_economic_calendar_rbi(
                        days_ahead, days_back=days_back, skip_cache=skip_cache
                    )
                )
                events = self._extract(res, "rbi")
            else:
                continue
            if events:
                out_events.extend(events)
                out_sources.append(src)
        return {"data": out_events, "sources": out_sources}

    def _extract(self, res: Any, tag: str) -> List[Dict[str, Any]]:
        if not isinstance(res, dict):
            return []
        data = res.get("data")
        if not isinstance(data, list) or not data:
            return []
        return [self._normalize(ev, tag) for ev in data if isinstance(ev, dict)]

    def _normalize(self, ev: Dict[str, Any], tag: str) -> Dict[str, Any]:
        raw_time = str(ev.get("time", ""))
        if len(raw_time) == 10:  # 仅日期无时间
            raw_time += " 08:30:00"
        iso = self._to_utc_iso(raw_time, self.SOURCE_TZ.get(tag, "UTC"))
        impact = str(ev.get("impact", "low")).lower()
        if impact not in ("high", "medium", "low"):
            impact = "low"
        return {
            "date": iso,
            "country": str(ev.get("country", "Global")),
            "event": str(ev.get("event", "")),
            "impact": impact,
            "previous": str(ev.get("previous", "")),
            "estimate": str(ev.get("estimate", "")),
            "actual": str(ev.get("actual", "")),
            "_src": tag,
        }

    def _to_utc_iso(self, raw_time: str, tz_name: str) -> str:
        today = datetime.now(timezone.utc)
        s = (raw_time or "").strip()
        if not s:
            return today.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            if "T" in s:
                dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
            elif len(s) >= 19:
                dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            elif len(s) >= 16:
                dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
            else:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            if _ZONEINFO and tz_name != "UTC":
                dt = dt.replace(tzinfo=_ZONEINFO(tz_name))
                iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            return iso
        except Exception:  # noqa: BLE001
            return s.replace(" ", "T") + "Z" if s else today.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _merge(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        best: Dict[tuple, Dict[str, Any]] = {}
        for ev in events:
            key = (
                ev["country"].strip().lower(),
                ev["event"].strip().lower(),
                ev["date"][:10],
            )
            existing = best.get(key)
            if existing is None:
                best[key] = ev
            elif self._completeness(ev) > self._completeness(existing):
                best[key] = ev
        return list(best.values())

    @staticmethod
    def _completeness(ev: Dict[str, Any]) -> int:
        return sum(1 for k in ("actual", "estimate", "previous") if ev.get(k))

    def _build_message(self, contributed: List[str]) -> str:
        if not contributed:
            return "⚠️ 所有宏观数据源均未返回数据，请检查各数据源 API Key 配置。"
        label = {
            "akshare": "AKShare(金十/百度/新浪)",
            "finnhub": "Finnhub",
            "dbnomics": "DBnomics(OECD G20 CPI)",
            "rbi": "RBI/WorldBank",
            "fred": "FRED",
        }
        names = [label.get(c, c) for c in contributed]
        return (
            f"✅ 宏观日历多源聚合完成，贡献源: {', '.join(names)}。"
            "FRED 权威序列已回填美国核心及国际 CPI 实际值，"
            "DBnomics(OECD G20) + RBI 已免费覆盖印度/巴西/墨西哥等新兴市场 CPI 盲区。"
        )


# 全局单例
macro_calendar_aggregator = MacroCalendarAggregator()
