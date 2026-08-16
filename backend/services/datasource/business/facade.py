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

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Any, Optional

from backend.core.metrics import (
    DATASOURCE_FACADE_MERGE,
    DATASOURCE_QUOTE_DEVIATION,
)
from backend.services.datasource import (
    DataSourceError,
    ErrorCode,
    ErrorInfo,
    Result,
    ResultStatus,
)
from backend.services.datasource.source_registry import datasource_registry


def _to_float(v: Any) -> Optional[float]:
    """安全转 float（None / 空 / 非数字返回 None，不臆造）。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
        # 新兴市场 CPI actual 兜底（与 fred 前瞻日历互补，权重略高于默认）
        "dbnomics": 55,
        "rbi": 55,
    }.get(name, 50)
    return int(os.getenv(f"DATASOURCE_{name.upper()}_BUSINESS_WEIGHT", str(default)))


def _detect_market(ticker: str) -> str:
    """按 ticker 判定市场（US / HK / CN）。

    输入为业务侧标准化格式（Futu 前缀），如 ``US.AAPL`` / ``HK.00700`` /
    ``SH.600000`` / ``SZ.000001``；兼容 ``AAPL`` / ``00700.HK`` / ``600000.SH`` 等
    原始写法。判定结果用于市场感知的源优先级路由。
    """
    s = (ticker or "").strip().upper()
    if not s:
        return "US"
    if s.startswith("HK.") or s.endswith(".HK") or ("HK:" in s):
        return "HK"
    if s.startswith(("SH.", "SZ.")) or s.endswith((".SH", ".SZ", ".SS")):
        return "CN"
    # 💡 裸代码 A 股识别（2026-08-14）：前端订阅/外部来源可能以裸代码形式存 A 股
    # （如 688777 / 300316 / 600667，无 SH./SZ. 前缀）。此前被 _detect_market 判为 US，
    # 导致 FUND_FLOW/QUOTE 走 futu(无 A 股权限) 失败。按 A 股代码段识别为 CN，
    # 使裸代码 A 股正确路由到 tushare/akshare（_MARKET_FLOW_PREFERENCE["CN"]）。
    # 规则：6 位纯数字，按上交所/深交所代码段判断。
    if _is_naked_cn_code(s):
        return "CN"
    return "US"


def _is_naked_cn_code(ticker: str) -> bool:
    """判断是否为无市场前缀的 A 股裸代码（6 位纯数字，按代码段识别 SH/SZ）。

    上交所(SH)：600/601/603/605/688/689/900
    深交所(SZ)：000/001/002/003/300/301/200
    """
    s = (ticker or "").strip()
    if len(s) != 6 or not s.isdigit():
        return False
    prefix = s[:3]
    if prefix in ("600", "601", "603", "605", "688", "689", "900"):
        return True
    if prefix in ("000", "001", "002", "003", "300", "301", "200"):
        return True
    return False


# 市场感知的源优先级（QUOTE / HISTORY 报价类 action）。
# 策略（2026-08-14）：Futu 真实报价首选（低延迟、港股原生覆盖好）；
# yfinance 经独立 YF 辅节点远程，作为行情兜底末位（比 futu 更"永远在线"，
# 一旦 Futu OpenD 未起可自动降级）；美股 Finnhub 备选、A股 AKShare/Tushare 备选。
# 仅列出声明了对应 action 能力的源，顺序即降级顺序（首=优先，末=兜底）。
_MARKET_QUOTE_PREFERENCE: dict[str, list[str]] = {
    "US": ["futu", "finnhub", "akshare", "yfinance"],  # yfinance 美股行情兜底
    "HK": ["futu", "akshare", "yfinance"],  # Finnhub 免费版无港股报价，排除；yfinance 末位兜底
    "CN": ["futu", "akshare", "tushare"],  # A股走 AKShare/Tushare，yfinance 非 A股源不加
}

# 新闻类 action 的源优先级：Finnhub 是美股新闻核心数据源，首选；
# 港股新闻主源是 Futu（富途个股资讯），且 Finnhub 免费版不支持港股代码，
# 故港股排除 finnhub，与 _MARKET_QUOTE_PREFERENCE["HK"] 保持一致；
# A股新闻走 AKShare（东方财富）。
_MARKET_NEWS_PREFERENCE: dict[str, list[str]] = {
    "US": ["finnhub", "yfinance", "akshare"],
    "HK": ["futu", "akshare", "yfinance"],
    "CN": ["akshare", "finnhub"],
}

# 资金流类 action (FUND_FLOW) 的市场感知源优先级。
# 注意：tushare moneyflow 仅支持 A股个股，港股/美股资金流走 Futu/AKShare，
# 避免港股 FUND_FLOW 被误路由到 tushare（router 报 unsupported action）。
_MARKET_FLOW_PREFERENCE: dict[str, list[str]] = {
    "US": ["futu", "akshare", "yfinance"],
    "HK": ["futu", "akshare", "yfinance"],  # tushare 仅 A股，港股排除
    "CN": ["tushare", "akshare", "futu"],
}

# 基本面类 action (FUNDAMENTAL / INFO) 的市场感知源优先级。
# DIST-SEC-05(2026-08-14): 此前 FUNDAMENTAL 无市场感知策略，默认退化为首个可用源（多为 FMP）。
# FMP 免费档对港股/中股基本面覆盖稀疏（profile/income_statement 常返回空），而 yfinance 对
# 港股(0772.HK)/美股覆盖稳定、akshare 对 A股覆盖稳定。故港股/中股基本面优先 yfinance/akshare，
# 美股仍 futu 首选（真实财务）+ fmp 兜底。
_MARKET_FUNDAMENTAL_PREFERENCE: dict[str, list[str]] = {
    "US": ["futu", "fmp", "yfinance"],
    "HK": ["yfinance", "akshare", "futu", "fmp"],  # FMP 港股稀疏，降到末位兜底
    "CN": ["akshare", "tushare", "yfinance"],
}


def _merge_calendar_events(results: list[Result]) -> list[dict]:
    """合并多源经济日历的 events。

    - 以 ``country + event`` 为键去重
    - ``actual`` 互补：fred 给前瞻（多数无 actual），dbnomics/rbi 给 CPI actual 兜底，
      任一源有 actual 即回填
    - 保留最先出现的源字段（country/event/time/impact/previous/estimate）
    """
    merged: dict[tuple[str, str], dict] = {}
    for r in results:
        data = r.data if isinstance(r.data, dict) else {}
        for ev in data.get("events", []) or []:
            if not isinstance(ev, dict):
                continue
            key = (ev.get("country", ""), ev.get("event", ""))
            if key not in merged:
                merged[key] = dict(ev)
            else:
                # actual 回填：本源有 actual 而主记录无，则补上
                if ev.get("actual") and not merged[key].get("actual"):
                    merged[key]["actual"] = ev["actual"]
                # estimate 互补（同理）
                if ev.get("estimate") and not merged[key].get("estimate"):
                    merged[key]["estimate"] = ev["estimate"]
    return list(merged.values())


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

    async def get_fundamental_merged(self, ticker: str) -> Result:
        """G1 · 真基本面三源合并（戳破假基本面）。

        并发拉取三路真实基本面，单源失败不影响全局（graceful degradation，
        符合零幻觉红线——缺失字段保留原值，不臆造、不静默降级为假数据）：

        - **Futu** (FINANCIALS + VALUATION)：经 OpenD 直连交易所的真实三大表
          + 估值明细（PE/PB/股息率/市值），港股/美股原生覆盖强。
        - **FMP** (FUNDAMENTAL)：profile + income_statement 兜底（美股覆盖好）。
        - **YFinance** (INFO)：info 字典估值（PE/PB/市值/52周区间），多市场兜底。

        返回统一结构：``{ "ticker", "sources": {源: 状态}, "futu": {...}, "fmp": {...}, "yfinance": {...} }``。
        全部源失败时返回 ``ALL_SOURCES_FAILED``，如实暴露而非假绿。
        """

        async def _safe_fetch(label: str, coro):
            try:
                return label, await coro
            except Exception as e:  # noqa: BLE001 - 单源崩溃不应拖垮合并
                logging.warning("get_fundamental_merged: 源 %s 异常: %s", label, e)
                return label, Result.error_result(
                    DataSourceError(
                        code=ErrorCode.INTERNAL_ERROR,
                        message=f"源 {label} 基本面合并异常: {e}",
                        source=label,
                    )
                )

        # 并发拉取三路（Futu 两 action 并行，FMP/YF 各一路）
        labels_and_coros = [
            ("futu", self._fetch_futu_fundamental(ticker)),
            ("fmp", self.get_fundamental(ticker, prefer_sources=["fmp"])),
            ("yfinance", self.get_fundamental_info(ticker, prefer_sources=["yfinance"])),
        ]
        outcomes = await asyncio.gather(*[_safe_fetch(src, c) for src, c in labels_and_coros])

        merged = {
            "ticker": ticker,
            "sources": {},
            "futu": None,
            "fmp": None,
            "yfinance": None,
        }
        any_ok = False
        for label, res in outcomes:
            if isinstance(res, Result) and res.is_success and res.data:
                any_ok = True
                merged[label] = res.data
                merged["sources"][label] = "ok"
            else:
                err_msg = res.error.message if isinstance(res, Result) and res.error else "unknown"
                merged["sources"][label] = f"failed: {err_msg}"

        if not any_ok:
            return Result.error_result(
                DataSourceError(
                    code=ErrorCode.ALL_SOURCES_FAILED,
                    message=f"基本面三源合并全部失败: {ticker}",
                    source="facade",
                )
            )

        merged["_merged_at"] = datetime.now().isoformat()
        return Result.success_result(merged, source="facade", remark="G1真基本面三源合并")

    async def _fetch_futu_fundamental(self, ticker: str) -> Result:
        """Futu 真基本面（三大表 + 估值明细）聚合为单 Result。

        经 DataSourceRouter 远程 futu 子服务（router action: FINANCIALS / VALUATION）。
        任一 action 失败则该源降级为 failed 段，不阻塞其他源。
        """

        # 优先源：futu（FINANCIALS/VALUATION 仅 futu 声明了 capability）
        async def _safe(action: str, coro):
            try:
                return action, await coro
            except Exception as e:  # noqa: BLE001
                logging.warning("futu 基本面 action %s 异常: %s", action, e)
                return action, None

        fin_res, val_res = await asyncio.gather(
            self._dispatch("FINANCIALS", {"ticker": ticker}, prefer_sources=["futu"], enable_merge=False),
            self._dispatch("VALUATION", {"ticker": ticker}, prefer_sources=["futu"], enable_merge=False),
        )

        data: dict[str, Any] = {}
        if isinstance(fin_res, Result) and fin_res.is_success:
            data["financials"] = fin_res.data
        if isinstance(val_res, Result) and val_res.is_success:
            data["valuation"] = val_res.data

        if not data:
            return Result.error_result(
                DataSourceError(
                    code=ErrorCode.ALL_SOURCES_FAILED,
                    message=f"futu 基本面两 action 均失败: {ticker}",
                    source="futu",
                )
            )
        return Result.success_result(data, source="futu", remark="Futu真基本面(财报+估值)")

    # ── G2: 港股卖空拥挤度监控 ──────────────────────────────────────────
    async def get_short_selling(self, ticker: str, mode: str = "rank") -> Result:
        """G2 · 卖空拥挤度监控（Futu 真卖空源 + HKEX/SFC 监管交叉验证）。

        依赖 F1 落地的 Futu ``SHORT_SELLING`` action（``rank`` 卖空榜 / ``daily`` 每日卖空量）
        + 已接 ``get_hk_share_margin``（HKEX 市场级卖空占比，监管交叉验证基准）。

        派生指标（零幻觉：缺失不臆造，T-1 红线）：
        - ``short_sale_ratio_median``：卖空榜中位数成交占比（市场拥挤度代理）
        - ``cross_validation``：Futu 占比 vs HKEX 市场级 ``short_volume_ratio`` 一致性（偏差%）
        - ``alert_signal``：占比突破阈值 → ``squeeze_candidate``（挤空候选）/ ``collapse_warning``（崩塌预警）

        T-1 红线：``daily`` 模式当日盘后 0 行 → 如实标 ``no_data``，严禁输出"卖空为 0"。
        """
        import statistics

        from backend.services.margin.hk_share import get_hk_share_margin

        mode = (mode or "rank").lower()
        if mode not in ("rank", "daily"):
            mode = "rank"

        async def _safe(label, coro):
            try:
                return label, await coro
            except Exception as e:  # noqa: BLE001
                logging.warning("get_short_selling: 源 %s 异常: %s", label, e)
                return label, None

        futu_coro = self._dispatch(
            "SHORT_SELLING",
            {"ticker": ticker, "sub_action": mode},
            prefer_sources=["futu"],
            enable_merge=False,
        )
        hk_coro = get_hk_share_margin()

        futu_res, hk_res = await asyncio.gather(_safe("futu", futu_coro), _safe("hkex", hk_coro))

        data: Dict[str, Any] = {
            "ticker": ticker,
            "mode": mode,
            "sources": {},
            "futu": None,
            "regulatory": None,
            "derived": None,
        }

        # ── Futu 真卖空源 ──
        futu_payload = None
        if isinstance(futu_res, tuple):
            fr, _ = futu_res
            if isinstance(fr, Result) and fr.is_success:
                futu_payload = fr.data
                data["sources"]["futu"] = "ok"
            else:
                err = fr.error.message if isinstance(fr, Result) and fr.error else "unknown"
                data["sources"]["futu"] = f"failed: {err}"
        if futu_payload is None:
            return Result.error_result(
                DataSourceError(
                    code=ErrorCode.ALL_SOURCES_FAILED,
                    message=f"卖空数据 Futu 源不可用: {ticker}",
                    source="futu",
                )
            )

        # T-1 红线：daily 0 行如实标 no_data
        if futu_payload.get("status") == "no_data":
            data["futu"] = futu_payload
            data["sources"]["futu"] = "no_data"
            data["_merged_at"] = datetime.now().isoformat()
            return Result.success_result(data, source="facade", remark="G2卖空(T-1无数据,未臆造0)")

        data["futu"] = futu_payload

        # ── 监管交叉验证（HKEX/SFC 市场级占比）──
        hk_ratio = None
        if isinstance(hk_res, tuple):
            hk_status, hk_payload = hk_res
            if hk_status == "success" and hk_payload and hk_payload.get("data"):
                hk_data = hk_payload["data"]
                hk_ratio = hk_data.get("short_volume_ratio")
                data["regulatory"] = {
                    "short_volume_ratio": hk_ratio,
                    "as_of": hk_data.get("as_of"),
                    "sources": hk_data.get("sources", []),
                    "note": hk_data.get("note", ""),
                }
                data["sources"]["hkex_sfc"] = "ok"
            else:
                data["sources"]["hkex_sfc"] = "unavailable"
        else:
            data["sources"]["hkex_sfc"] = "unavailable"

        # ── 派生指标（基于 Futu 卖空榜 DataFrame）──
        rows = futu_payload.get("data", [])
        derived: Dict[str, Any] = {}
        if mode == "rank" and rows:
            ratios = []
            for r in rows:
                st = _to_float(r.get("short_sell_turnover"))
                tt = _to_float(r.get("total_turnover")) or _to_float(r.get("turnover"))
                if st is not None and tt and tt > 0:
                    ratios.append(st / tt * 100)
            if ratios:
                median_ratio = statistics.median(ratios)
                derived["short_sale_ratio_median"] = round(median_ratio, 4)
                derived["short_sale_ratio_max"] = round(max(ratios), 4)
                derived["short_sale_ratio_min"] = round(min(ratios), 4)
                derived["rank_count"] = len(ratios)
                # 拥挤度分位：中位占比越高 → 越拥挤（阈值经验值，需历史回填校准）
                derived["crowding_level"] = "high" if median_ratio >= 15 else "mid" if median_ratio >= 8 else "low"

        # 交叉验证一致性：Futu 中位占比 vs HKEX 市场级占比
        if derived.get("short_sale_ratio_median") is not None and hk_ratio is not None:
            dev = (derived["short_sale_ratio_median"] - hk_ratio) / hk_ratio * 100 if hk_ratio else None
            derived["cross_validation_deviation_pct"] = round(dev, 2) if dev is not None else None
            derived["cross_validation_consistent"] = abs(dev) < 30 if dev is not None else None

        # 告警信号（供 AlertEngine 消费；实时订阅流后续迭代接）
        alert_signal = None
        if derived.get("crowding_level") == "high":
            alert_signal = {
                "type": "squeeze_candidate",
                "severity": "warning",
                "message": f"卖空成交占比中位 {derived['short_sale_ratio_median']}% 进入高位，挤空候选",
            }
        elif derived.get("cross_validation_consistent") is False:
            alert_signal = {
                "type": "collapse_warning",
                "severity": "info",
                "message": f"Futu 占比与 HKEX 监管值偏差 {derived['cross_validation_deviation_pct']}%，一致性异常",
            }
        derived["alert_signal"] = alert_signal
        data["derived"] = derived

        data["_merged_at"] = datetime.now().isoformat()
        return Result.success_result(data, source="facade", remark="G2卖空拥挤度监控(三源收口)")

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

    async def get_economic_calendar(
        self, days_ahead: int = 7, days_back: int = 0, prefer_sources: Optional[list[str]] = None
    ) -> Result:
        """宏观经济日历（fred / dbnomics / rbi 多源融合）。

        fred 提供前瞻事件日历（含 estimate），dbnomics/rbi 提供新兴市场 CPI
        actual 兜底回填。两路经 ``_merge`` 的 ``ECONOMIC_CALENDAR`` 分支做
        actual 互补合并、去重；全源失败返回 ``ALL_SOURCES_FAILED``。
        """
        return await self._dispatch(
            "ECONOMIC_CALENDAR",
            {"days_ahead": days_ahead, "days_back": days_back},
            prefer_sources=prefer_sources,
            enable_merge=True,
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
        candidates = self._select_source(action, prefer_sources, params=params)

        results: list[Result] = []
        last_err: Optional[Result] = None
        for src in candidates:
            res = await datasource_registry.fetch(src, action, params)
            if res.is_success:
                results.append(res)
                # 单源成功即可停止（除非需要多源融合）
                if not enable_merge:
                    break
            else:
                # 记录最后一个非限流错误，便于失败时溯源真实原因
                if not (res.is_rate_limited or (res.error and res.error.is_rate_limit_type)):
                    last_err = res

        if not results:
            # 全部失败：优先保留首个真实业务错误的溯源信息，避免被泛化掩盖
            if last_err is not None and last_err.error is not None:
                reason = f"action={action} 所有候选源失败: [{last_err.source}] {last_err.error.message}"
                return Result.make_error(
                    ErrorInfo.normal("ALL_SOURCES_FAILED", reason, retryable=last_err.error.retryable),
                    source="+".join(candidates),
                )
            last_err_fallback = ErrorInfo.normal(
                "ALL_SOURCES_FAILED", f"action={action} 所有候选源失败", retryable=True
            )
            return Result.make_error(last_err_fallback, source="+".join(candidates))

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

    def _select_source(
        self, action: str, prefer_sources: Optional[list[str]], params: Optional[dict[str, Any]] = None
    ) -> list[str]:
        """源选择策略：市场感知优先级 → 健康度过滤 → 限流退避过滤 → 权重排序。

        返回候选源列表（已排序，最优在前）。``prefer_sources`` 可临时覆盖排序。

        市场感知路由（2026-08-13）：QUOTE / HISTORY 报价类 action 按 ticker 判定
        市场（US/HK/CN），用市场专属源优先级覆盖默认全局权重：
          - Futu 作为真实报价首选（所有市场）
          - 美股 Finnhub 备选；A股/港股 AKShare/Tushare 备选
          - Finnhub 免费版无港股报价，港股候选源排除 finnhub
        """
        from backend.services.datasource.registry import rate_limit_registry

        params = params or {}
        market: Optional[str] = None
        action_upper = action.upper()
        quote_action = action_upper in ("QUOTE", "HISTORY")
        news_action = action_upper in ("COMPANY_NEWS", "MARKET_NEWS", "NEWS", "STOCK_NEWS")
        flow_action = action_upper == "FUND_FLOW"
        fundamental_action = action_upper in ("FUNDAMENTAL", "INFO")
        if quote_action or news_action or flow_action or fundamental_action:
            ticker = params.get("ticker") or params.get("symbol") or ""
            market = _detect_market(str(ticker))

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

        if market:
            preference = None
            if quote_action and market in _MARKET_QUOTE_PREFERENCE:
                preference = _MARKET_QUOTE_PREFERENCE[market]
            elif flow_action and market in _MARKET_FLOW_PREFERENCE:
                preference = _MARKET_FLOW_PREFERENCE[market]
            elif news_action and market in _MARKET_NEWS_PREFERENCE:
                preference = _MARKET_NEWS_PREFERENCE[market]
            elif fundamental_action and market in _MARKET_FUNDAMENTAL_PREFERENCE:
                preference = _MARKET_FUNDAMENTAL_PREFERENCE[market]
            if preference:
                # 市场感知：报价/新闻路由是排他性策略，严格按市场专属顺序走，
                # 仅保留 preference 中声明了对应 action 能力的源。
                # 不把 preference 之外的源追加到末尾——否则港股报价会兜底降级到
                # Finnhub(免费版返回假 0)，违背"港股报价排除 finnhub"的策略。
                available = {n for _, n in scored}
                ordered = [s for s in preference if s in available]
                if ordered:
                    return ordered

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
        elif action == "ECONOMIC_CALENDAR":
            # 宏观日历：fred 给前瞻日历（含 estimate），dbnomics/rbi 给新兴市场 CPI
            # actual 兜底。按 country+event 合并，actual 互补回填，去重。
            merged_events = _merge_calendar_events(results)
            primary = best.data if isinstance(best.data, dict) else {}
            merged = dict(primary)
            merged["events"] = merged_events
            merged["merged_sources"] = [r.source for r in results]
            best = Result.make_success(
                merged,
                source=best.source,
                latency_ms=best.latency_ms,
                cached=best.cached,
            )
            DATASOURCE_FACADE_MERGE.labels(action=action, mode="calendar_merge").inc()
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
