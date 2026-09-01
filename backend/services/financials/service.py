"""
FIN-04 · 财报服务编排（采集 → 归一 → 落库 → 读取）
==================================================

docs/28 §二「模块落位」里的服务层：路由只做校验与转发，所有业务在这。

三条铁律：
  1. **不直连外网**：一手 payload 一律经 `DataSourceRegistry.fetch("filings", ...)`（AGENTS §2/§4）
  2. **不阻塞事件循环**：归一化/勾稽等重计算卸载到进程池（`jobs.submit`）
  3. **缺失不补零**：源没给的科目就是 `None`，宁可界面留白也不造假数
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Callable, Mapping

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.financials_models import STATEMENTS, FinancialFact
from backend.domain.financials import textlayer
from backend.domain.financials.mapper import VersionedFact
from backend.services.datasource import ResultStatus
from backend.services.financials import coverage as coverage_audit
from backend.services.financials import jobs, parquet_store, peers, rag_bridge, repository, views
from backend.services.financials.repository import BASIS_LATEST

logger = structlog.get_logger(__name__)

SEC_SOURCE = "sec"
# Registry 里的源名（适配器 `name`）与事实溯源标签不是一回事：
# 前者用于选源，后者写进 financial_facts.source。
FILINGS_REGISTRY_SOURCE = "filings"
SNAPSHOT_PREFIX = "snap_financials_"

# 后台回填任务的强引用：asyncio 只持弱引用，不钉住可能被 GC 半路回收（任务永不收尾）
_background_tasks: set[Any] = set()

# FIN-09：单批回填实体上限（超过即 400，宁慢勿炸一手源限流）
MAX_BATCH_ENTITIES = 50


class FinancialsError(RuntimeError):
    """带 `error_code` 的业务异常（docs/28 §六错误码），由路由翻成统一响应体。"""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def resolve_entity_id(raw: str, *, symbol_to_cik: Mapping[str, str] | None = None) -> str:
    """把用户输入归一为内部 entity_id（US:CIK…  /  HK:00700  /  CN:600519）。

    - 已带市场前缀：原样大写返回（CIK 统一 10 位零填充）
    - 纯数字：6 位视为 A 股，1~5 位视为港股
    - 字母代码：美股 ticker，靠 `symbol_to_cik`（EDGAR 官方对照表）解析，查不到即报错
    """
    s = (raw or "").strip().upper()
    if not s:
        raise FinancialsError("fin_entity_not_found", "entity 不能为空", status_code=404)

    if ":" in s:
        market, code = s.split(":", 1)
        if market not in {"US", "HK", "CN"}:
            raise FinancialsError("fin_entity_not_found", f"未知市场: {market}", status_code=404)
        return f"{market}:{_normalize_code(market, code)}"

    if s.isdigit():
        # 10 位零填充是 EDGAR CIK 本尊；6 位是 A 股；1~5 位是港股（不足位补零）
        if len(s) == 10:
            return f"US:CIK{s}"
        market = "CN" if len(s) == 6 else "HK"
        return f"{market}:{_normalize_code(market, s)}"

    cik = (symbol_to_cik or {}).get(s)
    if not cik:
        raise FinancialsError(
            "fin_entity_not_found",
            f"无法解析实体 {raw}：美股请给 ticker（需已加载 EDGAR 对照表）或直接给 US:CIK…",
            status_code=404,
        )
    return f"US:{_normalize_code('US', cik)}"


def _normalize_code(market: str, code: str) -> str:
    code = code.strip().upper()
    if market != "US":
        return code.zfill(5) if market == "HK" else code
    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        raise FinancialsError("fin_entity_not_found", f"CIK 非法: {code}", status_code=404)
    return f"CIK{digits.zfill(10)}"


def parse_period_date(value: str | date | None, *, field: str = "as_of") -> date | None:
    """PIT 日期入参解析：格式错必须显式失败，禁止悄悄当「无约束」。"""
    if value is None or isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise FinancialsError("fin_bad_request", f"{field} 需为 YYYY-MM-DD: {value!r}", status_code=400) from exc


# ─────────────────────────────────────────
#  采集适配器：source → registry (action, params) 工厂
# ─────────────────────────────────────────

# 只经 Registry 取数（docs/23 §二铁律），不持任何外部 SDK
FACTS_FETCHERS: dict[str, Callable[[str], tuple[str, dict[str, Any]]]] = {
    SEC_SOURCE: lambda entity_id: ("COMPANY_FACTS", {"entity_id": entity_id}),
}
FILINGS_FETCHERS: dict[str, Callable[[str], tuple[str, dict[str, Any]]]] = {
    SEC_SOURCE: lambda entity_id: ("SUBMISSIONS", {"entity_id": entity_id}),
}

# 各源的归一化参数（列名属**参数**，标签映射一律在 concept_map.json）
SOURCE_PARAMS: dict[str, dict[str, Any]] = {
    SEC_SOURCE: {"taxonomy": "us-gaap"},
}


class FinancialsService:
    """财报编排。`registry` 可注入以便单测（禁打真实外网/真实子服务）。"""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    # ── 写：回填 ──

    async def backfill(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        source: str = SEC_SOURCE,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """全量回填一个实体：一手 payload → 进程池归一 → 落库 → 申报索引 → Parquet 宽表。

        `job_id` 由 `schedule_backfill` 传入（任务已登记）；直接调用时自行登记一个。
        """
        if source not in FACTS_FETCHERS:
            raise FinancialsError(
                "fin_source_degraded",
                f"源 {source} 的回填尚未接入（港A 数字层走 Futu/Tushare，见 docs/28 §1.2）",
                status_code=501,
            )

        owned_job = job_id is None
        if owned_job:
            job_id = jobs.create_job(entity_id=entity_id, source=source)
            await jobs.persist(job_id)

        try:
            # 采集失败也得把任务推到终态，否则前端只能对着 pending 转圈
            payload = await self._fetch_payload(source, entity_id)
            params = {"entity_id": entity_id, "source": source, **SOURCE_PARAMS.get(source, {})}
            # CPU 重算卸载到进程池，不占事件循环（路由不得同步阻塞）
            transformed = await jobs.submit(job_id, payload, params)
            facts = [_to_versioned(item) for item in transformed["facts"]]
            written = await repository.upsert_facts(session, facts)
            filings_written = await self._sync_filings(session, entity_id, source)
            snapshot_id = await self._write_wide_tables(session, entity_id)
        except FinancialsError as exc:
            if owned_job:
                await jobs.update_job_persisted(job_id, status="failed", error=exc.message[:500])
            raise
        except Exception as exc:  # noqa: BLE001 - 任务状态必须收敛，不能留 running
            logger.exception("财报回填失败", entity_id=entity_id, source=source)
            if owned_job:
                await jobs.update_job_persisted(job_id, status="failed", error=str(exc)[:500])
            raise FinancialsError("fin_backfill_failed", f"回填失败: {exc}", status_code=502) from exc

        result = {
            "job_id": job_id,
            "entity_id": entity_id,
            "source": source,
            "facts_written": written,
            "filings_written": filings_written,
            "snapshot_id": snapshot_id,
            "stats": transformed["stats"],
            "integrity": transformed["integrity"],
        }
        if owned_job:
            await jobs.update_job_persisted(job_id, status="success", progress=100, result=result)
        logger.info("财报回填完成", entity_id=entity_id, rows=written, snapshot=snapshot_id)
        return result

    async def run_backfill_job(
        self,
        session: AsyncSession,
        job_id: str,
        *,
        entity_id: str,
        source: str = SEC_SOURCE,
    ) -> None:
        """后台执行回填并推进任务状态（路由用 `asyncio.create_task` 挂起来）。"""
        await jobs.update_job_persisted(job_id, status="running", progress=10)
        try:
            result = await self.backfill(session, entity_id=entity_id, source=source, job_id=job_id)
        except FinancialsError as exc:
            await jobs.update_job_persisted(job_id, status="failed", error=exc.message[:500])
        except Exception as exc:  # noqa: BLE001 - 后台任务禁止把异常抛回事件循环
            logger.exception("回填后台任务异常", job_id=job_id)
            await jobs.update_job_persisted(job_id, status="failed", error=str(exc)[:500])
        else:
            await jobs.update_job_persisted(job_id, status="success", progress=100, result=result)

    def schedule_backfill(
        self,
        session_factory: Callable[[], Any],
        *,
        entity_id: str,
        source: str = SEC_SOURCE,
    ) -> str:
        """登记任务并挂后台执行，立刻返回 job_id（路由必须异步返回，不等采集）。

        后台任务**自持会话**：请求一返回，路由那个 `AsyncSession` 就进了 `async with`
        的退出流程，复用会把正在跑的回填拦腰折断（`Task is closed`）。
        """
        job_id = jobs.create_job(entity_id=entity_id, source=source)

        async def _run() -> None:
            await jobs.persist(job_id)  # 内存已建，快照进 PG（best-effort，失败不阻断）
            async with session_factory() as session:
                await self.run_backfill_job(session, job_id, entity_id=entity_id, source=source)

        task = asyncio.create_task(  # noqa: RUF006 - 引用存进 `_background_tasks`，跑完自动丢弃
            _run()
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return job_id

    async def _fetch_payload(self, source: str, entity_id: str) -> Mapping[str, Any]:
        """经 Registry 取一手 payload；失败一律语义化为 `fin_source_degraded`。"""
        action, params = FACTS_FETCHERS[source](entity_id)
        result = await self._registry_fetch(action, params)
        if result.status != ResultStatus.SUCCESS:
            raise self._degraded_error(source, result)
        data = result.data or {}
        if source == SEC_SOURCE and not (data.get("facts") or {}).get("us-gaap"):
            raise FinancialsError(
                "fin_no_xbrl_coverage",
                f"{entity_id} 无 us-gaap XBRL 事实（20-F/40-F 等未提交 XBRL 的申报）",
                status_code=404,
            )
        return data

    def _degraded_error(self, source: str, result: Any) -> FinancialsError:
        message = getattr(getattr(result, "error", None), "message", None) or f"{source} 取数失败"
        if result.status == ResultStatus.RATE_LIMITED:
            return FinancialsError("fin_source_degraded", f"一手源限流退避中: {message}", status_code=429)
        return FinancialsError("fin_source_degraded", f"一手源不可用: {message}", status_code=502)

    async def _registry_fetch(self, action: str, params: dict[str, Any]) -> Any:
        """经 Registry 取数；未注入时用全局 registry（惰性注册 filings 适配器）。"""
        if self._registry is not None:
            return await self._registry.fetch(FILINGS_REGISTRY_SOURCE, action, params)

        from backend.services.datasource.adapters.filings import ensure_filings_registered
        from backend.services.datasource.source_registry import datasource_registry

        ensure_filings_registered()
        return await datasource_registry.fetch(FILINGS_REGISTRY_SOURCE, action, params)

    async def _sync_filings(self, session: AsyncSession, entity_id: str, source: str) -> int:
        """申报归档索引：拿不到不阻断回填（数字层已入库），只记警告。"""
        builder = FILINGS_FETCHERS.get(source)
        if builder is None:
            return 0
        action, params = builder(entity_id)
        try:
            result = await self._registry_fetch(action, params)
        except Exception as exc:  # noqa: BLE001 - 归档索引是旁路，失败降级
            logger.warning("申报索引拉取失败", entity_id=entity_id, err=str(exc))
            return 0
        if result.status != ResultStatus.SUCCESS:
            logger.warning(
                "申报索引返回非成功",
                entity_id=entity_id,
                message=getattr(result.error, "message", None),
            )
            return 0
        records = build_filing_records(entity_id, result.data or {})
        if not records:
            return 0
        return await repository.upsert_filings(session, records)

    async def _write_wide_tables(self, session: AsyncSession, entity_id: str) -> str:
        """按 docs/19 目录约定落 Parquet 宽表（latest 口径，供因子/回测整包读）。"""
        snapshot_id = SNAPSHOT_PREFIX + date.today().strftime("%Y%m%d")
        facts = await repository.get_facts(session, entity_id=entity_id, limit=5000)
        for statement in STATEMENTS:
            rows = [f for f in facts if f.statement == statement]
            if not rows:
                continue
            view = views.build_statement_view(rows, entity_id=entity_id, statement=statement, basis=BASIS_LATEST)
            parquet_store.write_wide_table(
                [
                    {"concept": row["concept"], "values": dict(zip(view["periods"], row["values"]))}
                    for row in view["rows"]
                ],
                entity_id=entity_id,
                statement=statement,
                snapshot_id=snapshot_id,
                basis=BASIS_LATEST,
                currency=view["currency"],
                source_mix=view["source_mix"],
            )
        return snapshot_id

    # ── 读：视图装配 ──

    async def get_statements(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        statement: str = "income",
        basis: str = BASIS_LATEST,
        as_of: date | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        if statement not in STATEMENTS:
            raise FinancialsError("fin_bad_request", f"statement 非法: {statement}", status_code=400)
        if basis not in (repository.BASIS_AS_REPORTED, BASIS_LATEST):
            raise FinancialsError("fin_bad_request", f"basis 非法: {basis}", status_code=400)
        facts = await repository.get_facts(session, entity_id=entity_id, statement=statement, as_of=as_of, limit=limit)
        if not facts:
            raise FinancialsError("fin_entity_not_found", f"{entity_id} 无 {statement} 事实，需先回填", status_code=404)
        return views.build_statement_view(facts, entity_id=entity_id, statement=statement, basis=basis, as_of=as_of)

    async def get_facts(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        concept: str | None = None,
        statement: str | None = None,
        as_of: date | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        facts = await repository.get_facts(
            session, entity_id=entity_id, concept=concept, statement=statement, as_of=as_of, limit=limit
        )
        if not facts:
            raise FinancialsError("fin_entity_not_found", f"{entity_id} 无匹配的科目事实", status_code=404)
        return {
            "entity_id": entity_id,
            "as_of": as_of.isoformat() if as_of else None,
            "items": views.build_fact_view(facts),
        }

    async def get_filings(self, session: AsyncSession, *, entity_id: str, limit: int = 100) -> dict[str, Any]:
        records = await repository.get_filings(session, entity_id=entity_id, limit=limit)
        return {"entity_id": entity_id, "items": views.build_filing_view(records), "count": len(records)}

    async def get_restatements(self, session: AsyncSession, *, entity_id: str, limit: int = 200) -> dict[str, Any]:
        facts = await repository.get_restatements(session, entity_id=entity_id, limit=limit)
        return {"entity_id": entity_id, "items": views.build_restatement_view(facts), "count": len(facts)}

    async def get_analytics(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        as_of: date | None = None,
        market_cap: float | None = None,
    ) -> dict[str, Any]:
        """单公司分析引擎（docs/28 §5.1）：DuPont / 现金流质量 / F·Z·M / TTM。"""
        facts = await repository.get_facts(session, entity_id=entity_id, as_of=as_of, limit=5000)
        if not facts:
            raise FinancialsError("fin_entity_not_found", f"{entity_id} 无事实，需先回填", status_code=404)
        view = views.build_analytics_view(facts, as_of=as_of, market_cap=market_cap)
        if not view:
            raise FinancialsError("fin_entity_not_found", f"{entity_id} 无年报（FY）事实，无法出分析", status_code=404)
        return {"entity_id": entity_id, "as_of": as_of.isoformat() if as_of else None, **view}

    async def get_peers(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        concept: str = "revenue",
        peer_set: str | None = None,
    ) -> dict[str, Any]:
        """同业截面分位（docs/28 §5.2）：本体最近一期 fact 定位 frames 帧，一次拿全市场取值。

        `peer_set` 手工固定同业清单（逗号分隔实体）；不给则走全市场截面。
        样本 < 8 家 → `fin_peer_sample_too_small` 422，禁止出分位结论。
        """
        facts = await repository.get_facts(session, entity_id=entity_id, concept=concept, limit=200)
        if not facts:
            raise FinancialsError("fin_no_xbrl_coverage", f"{entity_id} 无 {concept} 事实，需先回填", status_code=404)
        target = max(facts, key=lambda f: (f.fiscal_period == "FY", f.period_end))
        if not target.source_tag:
            raise FinancialsError(
                "fin_bad_request", f"{concept} 事实缺原始标签（source_tag），无法定位 frames 截面", status_code=400
            )
        period = peers.frame_period(target.fiscal_year, target.fiscal_period, is_instant=target.period_start is None)
        if period is None:
            raise FinancialsError(
                "fin_bad_request",
                f"frames 无 {target.fiscal_period} 流量截面帧（Q4/H1/9M 用年度或季度累计替代）",
                status_code=400,
            )

        result = await self._registry_fetch(
            "FRAMES",
            {"taxonomy": "us-gaap", "concept": target.source_tag, "measure": target.unit or "USD", "frame": period},
        )
        if result.status != ResultStatus.SUCCESS:
            raise self._degraded_error(FILINGS_REGISTRY_SOURCE, result)
        try:
            cross_section = peers.frames_cross_section(result.data or {})
        except ValueError as exc:
            raise FinancialsError("fin_source_degraded", str(exc), status_code=502) from exc

        peer_ids = [resolve_entity_id(p) for p in peers.parse_peer_set(peer_set)]
        weights = await self._revenue_weights(session, [entity_id, *peer_ids]) if peer_ids else None
        try:
            view = peers.peer_view(cross_section, entity_id=entity_id, peer_ids=peer_ids, weights=weights)
        except ValueError as exc:
            raise FinancialsError("fin_no_xbrl_coverage", str(exc), status_code=404) from exc
        if view["insufficient"]:
            raise FinancialsError(
                "fin_peer_sample_too_small",
                f"同业样本仅 {view['sample_size']} 家（<{peers.PEER_MIN_SAMPLE}），禁止出分位结论",
                status_code=422,
            )
        return {
            "entity_id": entity_id,
            "concept": concept,
            "tag": target.source_tag,
            "frame": period,
            "basis": "peers" if peer_ids else "market",
            **view,
        }

    async def _revenue_weights(self, session: AsyncSession, entity_ids: list[str]) -> dict[str, float] | None:
        """收入加权权重：各 peer 最新年报 revenue（缺年报的 peer 不参与加权，不猜数）。"""
        weights: dict[str, float] = {}
        for eid in entity_ids:
            revs = await repository.get_facts(session, entity_id=eid, concept="revenue", limit=50)
            annual = [f for f in revs if f.fiscal_period == "FY"]
            if annual:
                latest = max(annual, key=lambda f: f.fiscal_year)
                if latest.value_latest:
                    weights[eid] = latest.value_latest
        return weights or None

    # ── FIN-08 · 文本层 ──

    async def get_text_diff(
        self,
        session: AsyncSession,
        *,
        entity_id: str,
        accession_a: str | None = None,
        accession_b: str | None = None,
    ) -> dict[str, Any]:
        """MD&A / 风险因素 YoY diff（docs/28 §5.3，Lazy Prices）。

        `accession_a/b` 指定相邻两年年报；缺省自动取最近两份 10-K。
        文本经 Registry `DOC_TEXT` 拉取（docs/28 §二：不直连外网），章节切分与 diff 在域层纯函数。
        """
        records = await repository.get_filings(session, entity_id=entity_id, limit=200)
        tenk = [r for r in records if (r.form_type or "").upper() == "10-K" and r.doc_url]

        def _pick(accn: str | None) -> Any:
            if accn:
                hit = next((r for r in tenk if r.accession_no == accn), None)
                if hit is None:
                    raise FinancialsError("fin_not_found", f"申报 {accn} 不存在或非 10-K/缺原文", status_code=404)
                return hit
            return None

        rec_a, rec_b = _pick(accession_a), _pick(accession_b)
        if rec_a is None or rec_b is None:
            ordered = sorted(tenk, key=lambda r: (r.fiscal_year or 0, r.filed_at or ""))
            if len(ordered) < 2:
                raise FinancialsError(
                    "fin_not_found",
                    f"{entity_id} 归档里不足两份 10-K（含原文 URL），无法做 YoY diff",
                    status_code=404,
                )
            rec_a, rec_b = ordered[-2], ordered[-1]

        async def _text(rec: Any) -> str:
            result = await self._registry_fetch("DOC_TEXT", {"doc_url": rec.doc_url})
            if result.status != ResultStatus.SUCCESS:
                raise self._degraded_error(FILINGS_REGISTRY_SOURCE, result)
            return (result.data or {}).get("text") or ""

        old_text, new_text = await asyncio.gather(_text(rec_a), _text(rec_b))
        # 词级 SequenceMatcher 在数万词章节上是秒级纯 CPU——卸到线程，别拿事件循环陪葬
        diff = await asyncio.to_thread(textlayer.yoy_diff, old_text, new_text)
        return {
            "entity_id": entity_id,
            "old": {"accession_no": rec_a.accession_no, "fiscal_year": rec_a.fiscal_year, "doc_url": rec_a.doc_url},
            "new": {"accession_no": rec_b.accession_no, "fiscal_year": rec_b.fiscal_year, "doc_url": rec_b.doc_url},
            **diff,
        }

    async def validate_extractions(self, items: list[Mapping[str, Any]]) -> dict[str, Any]:
        """港A PDF 定点抽取强制溯源校验（docs/28 §5.3）：100% 带 source_page + source_text。"""
        return textlayer.validate_extractions(items)

    async def ingest_filing(self, session: AsyncSession, *, entity_id: str, accession_no: str) -> dict[str, Any]:
        """FIN-08b：申报原文 → RAG 知识库（切分 + 向量化 + 幂等写，docs/28 §5.3）。

        文本经 Registry `DOC_TEXT` 拉取（不直连外网）；向量化/写库是同步链路，
        卸到线程执行。成功后回写 `FilingRecord.rag_indexed`，时间轴状态闭环。
        """
        records = await repository.get_filings(session, entity_id=entity_id, limit=200)
        rec = next((r for r in records if r.accession_no == accession_no), None)
        if rec is None or not rec.doc_url:
            raise FinancialsError("fin_not_found", f"申报 {accession_no} 不存在或缺原文 URL", status_code=404)

        result = await self._registry_fetch("DOC_TEXT", {"doc_url": rec.doc_url})
        if result.status != ResultStatus.SUCCESS:
            raise self._degraded_error(FILINGS_REGISTRY_SOURCE, result)
        text = (result.data or {}).get("text") or ""

        outcome = await asyncio.to_thread(rag_bridge.ingest_document, rec.doc_url, text)
        if outcome.get("status") != "success":
            raise FinancialsError("fin_source_degraded", outcome.get("message") or "RAG 入库失败", status_code=502)
        rec.rag_indexed = True
        await session.commit()
        logger.info(
            "[FIN-08b] 申报原文已灌入 RAG",
            entity_id=entity_id,
            accession_no=accession_no,
            chunks=outcome.get("chunks_written"),
        )
        return {
            "entity_id": entity_id,
            "accession_no": accession_no,
            "doc_url": rec.doc_url,
            "chunks_written": outcome.get("chunks_written", 0),
        }

    # ── FIN-09 · 数据运维（覆盖率 / 批量回填 / 定时快照）──

    async def get_coverage(self, session: AsyncSession, *, entity_id: str, years: int = 10) -> dict[str, Any]:
        """核心科目 × 最近 N 财年覆盖盘点（docs/28 §九：缺失显式列出，禁止补零）。"""
        facts = await repository.get_facts(session, entity_id=entity_id, limit=5000)
        return {"entity_id": entity_id, **coverage_audit.audit_coverage(facts, years=years)}

    def backfill_batch(
        self,
        session_factory: Callable[[], Any],
        *,
        entities: list[str],
        source: str = SEC_SOURCE,
    ) -> list[dict[str, str]]:
        """目标池批量回填：逐实体挂后台任务立刻返回 job_id（单批限流保护一手源）。"""
        if not entities:
            raise FinancialsError("fin_bad_request", "entities 不能为空", status_code=400)
        if len(entities) > MAX_BATCH_ENTITIES:
            raise FinancialsError(
                "fin_bad_request",
                f"单批最多 {MAX_BATCH_ENTITIES} 个实体（避免打爆一手源限流），请分批提交",
                status_code=400,
            )
        scheduled = [
            {"entity_id": e, "job_id": self.schedule_backfill(session_factory, entity_id=e, source=source)}
            for e in entities
        ]
        logger.info("[FIN-09] 批量回填已挂后台", count=len(scheduled), source=source)
        return scheduled

    async def refresh_daily_snapshot(self, session: AsyncSession) -> dict[str, Any]:
        """把全部已回填实体的宽表重写进当日快照（docs/19：因子/回测按 data_snapshot_id 整包读）。

        供定时 daemon 调用：即使当天没有新回填，引用链也有当日快照可用。
        """
        result = await session.execute(select(FinancialFact.entity_id).distinct())
        entities = sorted({row[0] for row in result})
        snapshot_id = ""
        for eid in entities:
            snapshot_id = await self._write_wide_tables(session, eid)
        logger.info("[FIN-09] 当日快照刷新完成", entities=len(entities), snapshot_id=snapshot_id)
        return {"snapshot_id": snapshot_id, "entities": len(entities)}


def build_filing_records(entity_id: str, submissions: Mapping[str, Any]) -> list[dict[str, Any]]:
    """EDGAR `submissions` → 申报归档记录（docs/28 §四 FilingRecord）。

    只收「有原文主文档」的行：缺 document 的附件类索引跳掉，不造空 URL。
    财年优先用 `fiscalYearFocus`，缺失则退到报告期所属年，两者都没再用披露年。
    """
    filings = submissions.get("filings") or {}
    recent = filings.get("recent") or {}
    if not isinstance(recent, Mapping):
        return []
    cik = str(submissions.get("cik") or "").strip()
    columns = (
        recent.get("form") or [],
        recent.get("accessionNumber") or [],
        recent.get("filingDate") or [],
        recent.get("primaryDocument") or [],
        recent.get("reportDate") or [],
        recent.get("fiscalYearFocus") or [],
    )

    out: list[dict[str, Any]] = []
    for form, accn, filed, doc, period, fy in zip(*columns):
        filed_at = _as_date(filed)
        if not accn or not filed_at or not doc:
            continue
        out.append(
            {
                "entity_id": entity_id,
                "form_type": str(form),
                "fiscal_year": _fiscal_year(fy, period, filed_at),
                "filed_at": filed_at,
                "accession_no": str(accn),
                "doc_url": _doc_url(cik, accn, doc),
                "lang": "en",
                "rag_indexed": False,
            }
        )
    return out


def _fiscal_year(fy_focus: Any, report_date: Any, filed_at: date) -> int:
    focus = _as_int(fy_focus)
    if focus:
        return focus
    period_end = _as_date(report_date)
    return period_end.year if period_end else filed_at.year


def _doc_url(cik: str, accession_no: str, document: str) -> str:
    accn = str(accession_no).replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0') or '0'}/{accn}/{document}"


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_versioned(item: Mapping[str, Any]) -> VersionedFact:
    """jobs 段产出的 dict → repository 需要的 VersionedFact（键已在 CPU 段补齐）。"""
    return VersionedFact(**dict(item))


financials_service = FinancialsService()
