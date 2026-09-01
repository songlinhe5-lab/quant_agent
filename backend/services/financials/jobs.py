"""
FIN-04 · 回填任务登记簿 + CPU 卸载
==================================

回填是「一次请求打 SEC 拿数 MB、再对几千行做归一化/勾稽」的重活，**禁止**在事件循环里
算（AGENTS §4：路由不得同步阻塞）。分工：

    主协程（I/O）      → DataSourceRegistry.fetch("filings", ...) 拿一手 payload
    进程池（CPU）      → `transform_payload`：归一化 + Q4 推导 + 勾稽（纯函数、可 pickle）
    主协程（写库）     → repository.upsert_facts / upsert_filings

本模块只管**任务状态**与**CPU 段卸载**，不碰 HTTP 也不碰 DB（那些在 service.py）。
内存 dict 是任务状态的 SSOT（低延迟热路径）；FIN-10 起另有一层 **best-effort PG 快照**
（`financial_jobs` 表）：写侧失败只告警不影响任务推进（回填幂等重放），读侧内存优先、
miss 落库——进程重启后任务状态不再凭空消失（历史遗留的 running 由
`mark_stale_failed` 在启动时收敛为 failed，不留给前端转圈）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Mapping

import structlog
from sqlalchemy import update as _sa_update

from backend.core.financials_models import FinancialsJob

logger = structlog.get_logger(__name__)

JobStatus = Literal["pending", "running", "success", "failed"]

_jobs: dict[str, dict[str, Any]] = {}
_session_factory: Callable[[], Any] | None = None  # async_sessionmaker；测试/未接线时为 None


def configure(session_factory: Callable[[], Any]) -> None:
    """接线上下文工厂（app 启动时调一次）；不调则纯内存行为，测试零成本。"""
    global _session_factory
    _session_factory = session_factory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_job(*, entity_id: str, source: str) -> str:
    """登记一个 pending 任务，返回 job_id。"""
    job_id = f"finbf_{uuid.uuid4().hex[:12]}"
    _jobs[job_id] = {
        "job_id": job_id,
        "entity_id": entity_id,
        "source": source,
        "status": "pending",
        "progress": 0,
        "result": {},
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    return job_id


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    """推进任务状态（progress / status / result / error）。"""
    job = _jobs.get(job_id)
    if job is None:  # pragma: no cover - 只会被本模块创建的 id 调用
        raise KeyError(f"unknown job_id: {job_id}")
    job.update(fields)
    job["updated_at"] = _now()
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    return dict(job) if job else None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    rows = sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)
    return [dict(j) for j in rows[:limit]]


def reset_jobs() -> None:
    """测试隔离用（只清内存；PG 快照不属进程状态，测试自行建/换库）。"""
    _jobs.clear()


# ── FIN-10 · PG 快照层（best-effort：持久化失败不报警不阻断任务推进）──


def _to_row(job: Mapping[str, Any]) -> FinancialsJob:
    return FinancialsJob(
        job_id=job["job_id"],
        entity_id=job["entity_id"],
        source=job["source"],
        status=job["status"],
        progress=job["progress"],
        result=job["result"] or None,
        error=job["error"],
        created_at=job["created_at"],
        updated_at=job["updated_at"],
    )


async def persist(job_id: str) -> None:
    """把内存 job 快照 upsert 进 PG（merge 按主键幂等）；未接线/失败均静默降级。"""
    job = _jobs.get(job_id)
    if job is None or _session_factory is None:
        return
    try:
        async with _session_factory() as session:
            await session.merge(_to_row(job))
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - 快照丢失可接受，任务在内存里继续跑
        logger.warning("财报任务 PG 快照失败（不影响回填推进）", job_id=job_id, error=str(exc))


async def update_job_persisted(job_id: str, **fields: Any) -> dict[str, Any]:
    """内存推进 + PG 快照一步到位（async 调用方专用；persist 失败不影响返回）。"""
    job = update_job(job_id, **fields)
    await persist(job_id)
    return job


async def get_job_any(job_id: str) -> dict[str, Any] | None:
    """内存优先，miss 落库（重启后前端照常查到终态/失败原因）。"""
    job = get_job(job_id)
    if job is not None:
        return job
    if _session_factory is None:
        return None
    try:
        async with _session_factory() as session:
            row = await session.get(FinancialsJob, job_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("财报任务 PG 读取失败", job_id=job_id, error=str(exc))
        return None
    if row is None:
        return None
    return {
        "job_id": row.job_id,
        "entity_id": row.entity_id,
        "source": row.source,
        "status": row.status,
        "progress": row.progress,
        "result": row.result or {},
        "error": row.error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def mark_stale_failed() -> int:
    """启动时收敛历史遗留：重启后没有任何进程能推进 pending/running，必须标 failed。"""
    if _session_factory is None:
        return 0
    try:
        async with _session_factory() as session:
            result = await session.execute(
                _sa_update(FinancialsJob)
                .where(FinancialsJob.status.in_(("pending", "running")))  # noqa: PLR6201
                .values(status="failed", error="interrupted by restart")
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - 表可能还没迁移，别拦启动
        logger.warning("财报任务残留状态收敛失败（表未迁移？）", error=str(exc))
        return 0
    return result.rowcount or 0


async def submit(job_id: str, payload: Mapping[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """把 payload 的归一化/勾稽计算卸载到进程池（不可 pickle 时自动回退线程）。

    与调用方解耦：本函数只依赖 `transform_payload` 这个模块级函数，因此可被 pickle。
    """
    from backend.core.cpu_pool import run_cpu_bound

    update_job(job_id, status="running", progress=40)
    result = await run_cpu_bound(transform_payload, dict(payload), dict(params))
    update_job(job_id, progress=80)
    return result


# ─────────────────────────────────────────
#  CPU 段：payload → 待落库事实（纯计算，可在子进程执行）
# ─────────────────────────────────────────


def transform_payload(payload: Mapping[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """归一化 + 累计拆分 + 勾稽，返回可直接喂给 repository 的 dict 列表。

    params: entity_id / source / taxonomy / fiscal_year_end_month
    返回: {"facts": [...], "stats": {...}, "integrity": {...}}
    """
    from backend.domain.financials.checks import CHECK_STATEMENTS, failed_check_names
    from backend.domain.financials.mapper import ConceptMapper, from_companyfacts, from_rows
    from backend.domain.financials.periods import split_ytd

    entity_id = str(params["entity_id"])
    source = str(params.get("source") or "sec")
    taxonomy = str(params.get("taxonomy") or "us-gaap")
    fy_end_month = int(params.get("fiscal_year_end_month") or 12)

    raw = payload.get("facts") or payload.get("rows") or []
    if isinstance(raw, dict) or not raw:
        raw_facts = from_companyfacts(payload, taxonomy=taxonomy)
    else:
        raw_facts = from_rows(
            raw,
            taxonomy=taxonomy,
            tag_field=str(params.get("tag_field") or "tag"),
            value_field=str(params.get("value_field") or "value"),
            start_field=params.get("start_field"),
            end_field=params.get("end_field"),
            filed_field=params.get("filed_field"),
            accn_field=params.get("accn_field"),
            default_unit=str(params.get("unit") or ""),
        )

    mapper = ConceptMapper(source=source, default_taxonomy=taxonomy)
    normalized = split_ytd(mapper.normalize(raw_facts, entity_id=entity_id), fy_end_month)

    # 勾稽按「同一期末」的科目值跑：存量（start=None）与流量科目在概念上不重叠，
    # 同桶不会互盖；但 balance_identity 只有时点科目能凑齐，所以必须带时点值。
    # 推导值（Q4 = FY − 9M）不参与：它和期末撞桶，拿算出来的数去验等于自己验自己。
    by_period_end: dict[Any, dict[str, float]] = {}
    for fact in normalized:
        if fact.derived:
            continue
        by_period_end.setdefault(fact.period_end, {})[fact.concept] = fact.value
    period_failures: dict[Any, list[str]] = {}
    for end, values in by_period_end.items():
        if failures := failed_check_names(values):
            period_failures[end] = failures

    versioned = mapper.collapse_versions(normalized)
    facts: list[dict[str, Any]] = []
    for fact in versioned:
        # 失败只标注参与该校验的那张报表（docs/28 §3.4：不丢数、也不错标）
        names = [n for n in period_failures.get(fact.period_end, []) if CHECK_STATEMENTS.get(n) == fact.statement]
        facts.append(_versioned_to_dict(fact, names))

    return {
        "facts": facts,
        "stats": mapper.stats,
        "integrity": {
            "failed_periods": {end.isoformat(): names for end, names in period_failures.items()},
            "checked_periods": len(by_period_end),
        },
    }


def _versioned_to_dict(fact: Any, check_failed: list[str]) -> dict[str, Any]:
    """VersionedFact → repository 可读的 dict（date 保留对象，SQLAlchemy 直收）。

    勾稽标注写在**事实本身**（`check_failed`），仓储层逐条读，避免批量参数串期。
    """
    fact.check_failed = list(check_failed)
    return {
        "entity_id": fact.entity_id,
        "concept": fact.concept,
        "statement": fact.statement,
        "period_start": fact.period_start,
        "period_end": fact.period_end,
        "unit": fact.unit,
        "value_as_reported": fact.value_as_reported,
        "value_latest": fact.value_latest,
        "restated": fact.restated,
        "derived": fact.derived,
        "filed_as_reported": fact.filed_as_reported,
        "filed_latest": fact.filed_latest,
        "accession_no": fact.accession_no,
        "source": fact.source,
        "source_tag": fact.source_tag,
        "versions": fact.versions,
        "check_failed": list(fact.check_failed),
    }
