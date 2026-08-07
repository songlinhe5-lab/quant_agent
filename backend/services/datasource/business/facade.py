"""
DataServiceFacade — 业务聚合 Facade（BE-ARCH-06a）

在 DataSourceInterface 薄适配器之上，提供面向业务的语义接口，并收口：
  · 策略逻辑：源选择权重、多源融合、报价一致性校验
  · 业务级检测：Stale 检测、字段完整性、跨源偏差告警
  · 归一化：统一 OHLCV / 币种 / 时间粒度 / 复权
  · 业务缓存 + 命中率统计

铁律（docs/23 §二）：Facade 只能通过 ``datasource_registry.fetch`` 取数，禁止直接
import 具体数据源库（yfinance/futu/akshare）或直接 httpx.get 外部地址。

设计文档：docs/23. 业务数据源聚合Facade设计.md
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from backend.core.metrics import (
    DATASOURCE_FACADE_MERGE,
    DATASOURCE_QUOTE_DEVIATION,
)
from backend.services.datasource import ErrorInfo, Result, ResultStatus
from backend.services.datasource.source_registry import datasource_registry

# ────────────────────────────────────────────────────────────────────────────
# 配置（env 可覆盖）
# ────────────────────────────────────────────────────────────────────────────


def _business_weight(name: str) -> int:
    """业务权重（默认，可被 env 覆盖）。值越高越优先被选为源。"""
    default = {
        "futu": 100,
        "fred": 90,
        "yfinance": 80,
        "finnhub": 75,
        "fmp": 70,
        "akshare": 60,
    }.get(name, 50)
    return int(os.getenv(f"DATASOURCE_{name.upper()}_BUSINESS_WEIGHT", str(default)))


# 各 action 的新鲜度阈值（秒）；超过即判 stale
_STALE_THRESHOLD_SEC = {
    "QUOTE": 30,
    "FUND_FLOW": 300,
    "HISTORY": 3600,
    "OPTION_CHAIN": 3600,
    "FUNDAMENTAL": 86400,
    "COMPANY_NEWS": 600,
    "INFO": 86400,
    "WARRANT_CHAIN": 300,
    "SCREEN_STOCKS": 600,
    "HSGT_HOLDERS": 3600,
    "MACRO_SERIES": 86400,
}

# 多源报价偏差阈值（百分比）；超过即触发偏差告警
_QUOTE_DEVIATION_PCT = float(os.getenv("DATASOURCE_QUOTE_DEVIATION_PCT", "0.5"))


class DataServiceFacade:
    """业务聚合 Facade：向上提供业务语义，向下经 Registry 取数。

    不直接持有任何具体数据源实例，只通过 datasource_registry.fetch 取数。
    """

    # ── 业务语义接口（领域方法，由 market.py 等子模块扩展；此处给通用实现）──

    async def get_quote(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """行情快照：策略选源 → 多源融合 → 一致性检测 → 归一化。"""
        return await self._dispatch(
            "QUOTE",
            {"ticker": ticker},
            prefer_sources=prefer_sources,
            enable_merge=True,
        )

    async def get_history(
        self,
        ticker: str,
        ktype: str = "K_DAY",
        num: int = 60,
        prefer_sources: Optional[list[str]] = None,
    ) -> Result:
        """历史 K 线：选源 → 取数 → OHLCV 归一化（时间粒度/复权/币种）。"""
        return await self._dispatch(
            "HISTORY",
            {"ticker": ticker, "ktype": ktype, "num": num},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_fund_flow(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """当日主力资金流。"""
        return await self._dispatch(
            "FUND_FLOW",
            {"ticker": ticker},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_option_chain(
        self,
        ticker: str,
        expiration_date: str = "",
        prefer_sources: Optional[list[str]] = None,
    ) -> Result:
        """期权链及 OCC 合约代码。"""
        return await self._dispatch(
            "OPTION_CHAIN",
            {"ticker": ticker, "expiration_date": expiration_date},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_fundamental(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """个股基本面（PE/PB/ROE/做空比例等）。"""
        return await self._dispatch(
            "FUNDAMENTAL",
            {"ticker": ticker},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_fundamental_info(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """公司概况 / 财务详情（profile / income_statement 等）。"""
        return await self._dispatch(
            "INFO",
            {"ticker": ticker},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_company_news(
        self, ticker: str, days_back: int = 3, prefer_sources: Optional[list[str]] = None
    ) -> Result:
        """个股新闻与公告。"""
        return await self._dispatch(
            "COMPANY_NEWS",
            {"ticker": ticker, "days_back": days_back},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_warrant_chain(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """窝轮链（Futu 专属能力）。"""
        return await self._dispatch(
            "WARRANT_CHAIN",
            {"ticker": ticker},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def screen_stocks(self, market: str, filters: Any, prefer_sources: Optional[list[str]] = None) -> Result:
        """条件选股（Futu 专属能力）。"""
        return await self._dispatch(
            "SCREEN_STOCKS",
            {"market": market, "filters": filters},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_hsgt_holders(self, symbol: str, prefer_sources: Optional[list[str]] = None) -> Result:
        """沪深港通持股数据（AKShare 专属能力）。"""
        return await self._dispatch(
            "HSGT_HOLDERS",
            {"symbol": symbol},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_insider_transactions(
        self, ticker: str, limit: int = 20, prefer_sources: Optional[list[str]] = None
    ) -> Result:
        """高管内幕交易记录（Finnhub 能力）。"""
        return await self._dispatch(
            "INSIDER_TRADING",
            {"ticker": ticker, "limit": limit},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    async def get_macro_series(
        self, series_id: str, limit: int = 100, prefer_sources: Optional[list[str]] = None
    ) -> Result:
        """宏观经济序列（FRED 等）。"""
        return await self._dispatch(
            "MACRO_SERIES",
            {"series_id": series_id, "limit": limit},
            prefer_sources=prefer_sources,
            enable_merge=False,
        )

    # ── 内部调度原语 ──

    async def _dispatch(
        self,
        action: str,
        params: dict[str, Any],
        prefer_sources: Optional[list[str]] = None,
        enable_merge: bool = False,
    ) -> Result:
        """统一调度：选源 → 取数（可多源）→ 融合 → 检测 → 归一化。"""
        candidates = self._select_source(action, prefer_sources)

        results: list[Result] = []
        for src in candidates:
            res = await datasource_registry.fetch(src, action, params)
            if res.is_success:
                results.append(res)
            # 单源成功即可停止（除非需要多源融合）
            if results and not enable_merge:
                break

        if not results:
            # 全部失败：回退首个非限流错误，保留溯源信息
            last_err = ErrorInfo.normal("ALL_SOURCES_FAILED", f"action={action} 所有候选源失败", retryable=True)
            return Result.make_error(last_err, source="+".join(candidates))

        merged = self._merge(action, results) if enable_merge else results[0]
        DATASOURCE_FACADE_MERGE.labels(
            action=action, mode=("multi" if enable_merge and len(results) > 1 else "single")
        ).inc()
        # 业务级检测 + 归一化
        stale = self._detect_stale(merged.data, action)
        if stale is not None and merged.status == ResultStatus.SUCCESS:
            # 标记降级但不丢弃数据，供上层告警
            merged = Result(
                status=ResultStatus.DEGRADED,
                data=merged.data,
                source=merged.source,
                latency_ms=merged.latency_ms,
                cached=merged.cached,
                error=ErrorInfo.normal("DATA_STALE", stale, retryable=True),
            )
        merged.data = self._normalize(merged.data, action)
        return merged

    # ── 策略原语 ──

    def _select_source(self, action: str, prefer_sources: Optional[list[str]]) -> list[str]:
        """源选择策略：健康度过滤 → 限流退避过滤 → 业务权重排序。

        返回候选源列表（已排序，最优在前）。``prefer_sources`` 可临时覆盖排序。
        """
        from backend.services.datasource.registry import rate_limit_registry

        names = datasource_registry.list_names()
        scored: list[tuple[int, str]] = []
        for name in names:
            src = datasource_registry.get(name, action)
            if src is None:
                continue  # 不可用或不支持该 action
            throttler = rate_limit_registry.get_throttler(name)
            if throttler.should_throttle():
                continue  # 限流退避期，跳过（与 registry 主路径一致）
            weight = _business_weight(name)
            scored.append((weight, name))

        if prefer_sources:
            # 临时偏好：把 prefer 的源提到最前，其余按权重
            pref = [s for s in prefer_sources if any(s == n for _, n in scored)]
            rest = [n for w, n in sorted(scored, reverse=True)]
            return pref + [n for n in rest if n not in pref]

        return [n for _, n in sorted(scored, reverse=True)]

    @staticmethod
    def _merge(action: str, results: list[Result]) -> Result:
        """多源融合：单源直接采用；多源按新鲜度选最优，记录偏差指标。"""
        if len(results) == 1:
            return results[0]

        # 多源：取延迟最低（新鲜度高）者为主，其余做一致性校验
        best = min(results, key=lambda r: r.latency_ms)
        if action == "QUOTE":
            prices = [
                float(r.data.get("last_price", r.data.get("price", 0))) for r in results if isinstance(r.data, dict)
            ]
            if len(prices) >= 2:
                spread = max(prices) - min(prices)
                mid = sum(prices) / len(prices)
                dev_pct = (spread / mid * 100.0) if mid else 0.0
                if dev_pct > _QUOTE_DEVIATION_PCT:
                    DATASOURCE_QUOTE_DEVIATION.labels(source=best.source).inc()
                    DATASOURCE_FACADE_MERGE.labels(action=action, mode="deviation").inc()
        return best

    def _detect_stale(self, data: Any, action: str) -> Optional[str]:
        """业务级检测：数据新鲜度（阈值按 action）、字段完整性。

        返回告警文案；无问题返回 None。
        """
        threshold = _STALE_THRESHOLD_SEC.get(action, 3600)
        # 优先用结果自带的时间戳（若有）；用 is not None 判断避免 0.0 被当作 falsy
        ts = None
        if isinstance(data, dict):
            for key in ("timestamp", "update_time", "time"):
                if data.get(key) is not None:
                    ts = data.get(key)
                    break
        if ts is not None:
            try:
                age = time.time() - float(ts)
                if age > threshold:
                    return f"{action} 数据延迟 {age:.0f}s 超过阈值 {threshold}s"
            except (TypeError, ValueError):
                pass

        # 字段完整性（QUOTE 关键字段）
        if action == "QUOTE" and isinstance(data, dict):
            if not any(k in data for k in ("last_price", "price", "close")):
                return "QUOTE 缺少价格字段"
        return None

    @staticmethod
    def _normalize(data: Any, action: str) -> Any:
        """归一化：统一 OHLCV 字段名（小写下划线）、时间字段、币种标注、复权标记。

        v0.1：做字段名对齐与币种推断；不做多源拼接（见 docs/23 §六 开放问题）。
        """
        if not isinstance(data, dict):
            return data

        out = dict(data)
        # OHLCV 统一键（兼容常见别名）
        alias = {
            "open": ("Open", "o"),
            "high": ("High", "h"),
            "low": ("Low", "l"),
            "close": ("Close", "c"),
            "volume": ("Volume", "vol", "v"),
        }
        for canon, keys in alias.items():
            if canon not in out:
                for k in keys:
                    if k in out:
                        out[canon] = out[k]
                        break

        # 时间字段统一为 time
        if "time" not in out:
            for k in ("date", "datetime", "ts", "timestamp"):
                if k in out:
                    out["time"] = out[k]
                    break

        # 币种标注：缺失则按 ticker 后缀推断
        if "currency" not in out and "ticker" in out:
            t = str(out["ticker"])
            if t.endswith(".HK") or t.startswith("0") and len(t) >= 5:
                out["currency"] = "HKD"
            else:
                out["currency"] = "USD"

        # 复权标记默认 qfq
        if action == "HISTORY" and "adjust" not in out:
            out["adjust"] = "qfq"
        return out


# 全局单例（供 Tools / 业务逻辑直接调用）
data_service = DataServiceFacade()
