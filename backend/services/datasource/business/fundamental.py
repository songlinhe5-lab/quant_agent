"""
基本面领域业务适配器（BE-ARCH-06b / FIN-04）

在 DataServiceFacade 之上，提供面向「基本面」语义的封装：get_fundamental /
get_fundamental_info。底层统一经 ``data_service._dispatch`` 走
DataSourceRegistry → Router → 薄适配器，不直连任何数据源库。

FIN-04 起追加「一手财报」通路（docs/28 §二 Facade 收口）：
``get_statements`` / ``get_filings`` 读 financial_facts / filings 双时间轴存储，
与既有二手聚合快照 `get_fundamental` **并存不混用**——调用方必须能从返回体里
看清 source（sec / futu / tushare）与口径（as_reported / latest）。

设计文档：docs/23. 业务数据源聚合Facade设计.md · docs/28. 公司财报看板架构设计.md
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Optional

from backend.core.database import AsyncSessionLocal
from backend.core.logger import logger
from backend.services.datasource.business.facade import DataServiceFacade, data_service
from backend.services.financials import repository
from backend.services.financials import service as financials_service_module
from backend.services.financials.service import FinancialsService, parse_period_date, resolve_entity_id

# ticker → CIK 对照表：SEC 侧 7 天缓存，主服务侧再加进程缓存，避免每票回填都回源取表
_SYMBOLS_TTL_SEC = float(60 * 60 * 24)
_symbols_cache: tuple[float, dict[str, str]] | None = None


class FundamentalDataService:
    """基本面领域业务适配器。"""

    def __init__(
        self,
        facade: DataServiceFacade | None = None,
        financials: FinancialsService | None = None,
        session_factory: Any | None = None,
    ) -> None:
        self._facade = facade or data_service
        self._financials = financials or financials_service_module.financials_service
        self._session_factory = session_factory or AsyncSessionLocal

    def _session(self) -> Any:
        return self._session_factory()

    async def get_fundamental(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """个股基本面（PE/PB/ROE/做空比例等）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_fundamental(ticker, prefer_sources=prefer_sources)

    async def get_fundamental_info(self, ticker: str, prefer_sources: Optional[list[str]] = None) -> Any:
        """公司概况 / 财务详情（profile / income_statement 等）。"""
        self._validate_ticker(ticker)
        return await self._facade.get_fundamental_info(ticker, prefer_sources=prefer_sources)

    # ── FIN-04 · 一手财报（双时间轴事实层）──

    async def get_statements(
        self,
        entity: str,
        *,
        statement: str = "income",
        basis: str = repository.BASIS_LATEST,
        as_of: str | date | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """多期报表（common-size / YoY / 勾稽摘要随视图一起返回）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_statements(
                session,
                entity_id=entity_id,
                statement=statement,
                basis=basis,
                as_of=parse_period_date(as_of),
                limit=limit,
            )

    async def get_facts(
        self,
        entity: str,
        *,
        concept: str | None = None,
        statement: str | None = None,
        as_of: str | date | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """科目级明细（含双时间轴溯源）；传 `as_of` 即 PIT 查询。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_facts(
                session,
                entity_id=entity_id,
                concept=concept,
                statement=statement,
                as_of=parse_period_date(as_of),
                limit=limit,
            )

    async def get_filings(self, entity: str, *, limit: int = 100) -> dict[str, Any]:
        """申报归档时间轴（原文链接 + RAG 索引状态）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_filings(session, entity_id=entity_id, limit=limit)

    async def get_restatements(self, entity: str, *, limit: int = 200) -> dict[str, Any]:
        """重述 diff 清单（首次披露 vs 最新）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_restatements(session, entity_id=entity_id, limit=limit)

    async def get_analytics(
        self,
        entity: str,
        *,
        as_of: str | date | None = None,
        market_cap: float | None = None,
    ) -> dict[str, Any]:
        """单公司分析引擎（DuPont / 现金流质量 / F·Z·M / TTM）。market_cap 由行情侧传入。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_analytics(
                session, entity_id=entity_id, as_of=parse_period_date(as_of), market_cap=market_cap
            )

    async def get_peers(self, entity: str, *, concept: str = "revenue", peer_set: str | None = None) -> dict[str, Any]:
        """同业截面分位（frames 一次拿全市场，peer_set 可手工固定同业清单）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_peers(session, entity_id=entity_id, concept=concept, peer_set=peer_set)

    async def get_text_diff(
        self, entity: str, *, accession_a: str | None = None, accession_b: str | None = None
    ) -> dict[str, Any]:
        """MD&A / 风险因素 YoY diff（docs/28 §5.3 Lazy Prices）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_text_diff(
                session, entity_id=entity_id, accession_a=accession_a, accession_b=accession_b
            )

    async def validate_extractions(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """港A PDF 定点抽取强制溯源校验（100% 带 source_page + source_text）。"""
        return await self._financials.validate_extractions(items)

    async def ingest_filing(self, entity: str, *, accession_no: str) -> dict[str, Any]:
        """FIN-08b：申报原文 → RAG 知识库（切分 + 向量化 + 幂等写）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.ingest_filing(session, entity_id=entity_id, accession_no=accession_no)

    async def get_coverage(self, entity: str, *, years: int = 10) -> dict[str, Any]:
        """FIN-09：核心科目 × 最近 N 财年覆盖盘点（缺失显式列出，禁止补零）。"""
        async with self._session() as session:
            entity_id = await resolve_entity(entity)
            return await self._financials.get_coverage(session, entity_id=entity_id, years=years)

    def backfill_batch(self, entities: list[str], *, source: str = "sec") -> list[dict[str, str]]:
        """FIN-09：目标池批量回填，逐实体挂后台任务立刻返回 job_id。"""
        return self._financials.backfill_batch(self._session, entities=entities, source=source)

    async def backfill(
        self,
        entity: str,
        *,
        source: str = "sec",
        background: bool = True,
    ) -> dict[str, Any]:
        """历史回填。默认挂后台并立刻返回 job_id（禁止在请求里等采集完成）。

        后台路径**不开自己的会话**：`schedule_backfill` 会拿会话工厂在后台任务里
        自己 `async with`，避免请求返回时会话被提前关闭。
        """
        entity_id = await resolve_entity(entity)
        if not background:
            async with self._session() as session:
                return await self._financials.backfill(session, entity_id=entity_id, source=source)
        job_id = self._financials.schedule_backfill(self._session, entity_id=entity_id, source=source)
        return {"job_id": job_id, "entity_id": entity_id, "status": "pending"}

    @staticmethod
    def _validate_ticker(ticker: str) -> None:
        if not ticker or not str(ticker).strip():
            raise ValueError("ticker 不能为空")


async def resolve_entity(entity: str) -> str:
    """用户输入（ticker / CIK / 港A代码）→ 内部 entity_id。

    已是 `US:CIK…` / `HK:…` / `CN:…` 的直接归一；裸美股 ticker 需查 EDGAR 对照表，
    查不到即抛 `fin_entity_not_found`（不猜 CIK）。

    URL 路径里冒号容易被转义吃掉，故同时接受 `US-CIK0000320193` 写法（- 还原为 :）。
    """
    s = (entity or "").strip().upper()
    if s[:2] in {"US", "HK", "CN"} and s[2:3] == "-":
        s = s[:2] + ":" + s[3:]  # US-CIK0000320193 → US:CIK0000320193
    needs_symbols = ":" not in s and not s.isdigit()
    symbol_map = await load_symbol_to_cik() if needs_symbols else None
    return resolve_entity_id(s, symbol_to_cik=symbol_map)


async def load_symbol_to_cik(*, force_reload: bool = False) -> dict[str, str]:
    """ticker → 10 位 CIK（经 Registry 取 SEC 官方对照表，进程内 TTL 缓存）。"""
    global _symbols_cache
    now = time.monotonic()
    if _symbols_cache and not force_reload and now - _symbols_cache[0] < _SYMBOLS_TTL_SEC:
        return _symbols_cache[1]

    from backend.services.datasource.adapters.filings import ensure_filings_registered
    from backend.services.datasource.source_registry import datasource_registry

    ensure_filings_registered()
    try:
        result = await datasource_registry.fetch("filings", "SYMBOLS", {})
    except Exception as exc:  # noqa: BLE001  选源/传输炸穿也归到“对照表不可用”，不能让读路径冒 500
        logger.warning(f"[FIN-04] SEC 对照表拉取异常: {exc}")
        result = None
    payload = result.data if getattr(result, "status", None) and result.status.value == "success" else None
    if not isinstance(payload, dict):
        if _symbols_cache:  # 拉表失败但有旧缓存：用旧的，不阻断查询
            return _symbols_cache[1]
        raise financials_service_module.FinancialsError(
            "fin_source_degraded", "SEC ticker 对照表不可用，请改用 US:CIK… 形式", status_code=502
        )

    mapping = {
        str(row.get("ticker", "")).upper(): str(int(row["cik_str"])).zfill(10)
        for row in payload.values()
        if isinstance(row, dict) and row.get("ticker") and row.get("cik_str")
    }
    _symbols_cache = (now, mapping)
    return mapping


def reset_symbols_cache() -> None:
    """测试隔离用。"""
    global _symbols_cache
    _symbols_cache = None


# 领域单例
fundamental_data_service = FundamentalDataService()
