"""
专家团对外统一入口
封装 Orchestrator，提供会话管理 + 双层持久化 (Redis 热 + PG 冷)
"""

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from backend.services.expert_team.expert_registry import list_scenarios
from backend.services.expert_team.models import (
    AnalyzeRequest,
    DebateSession,
    ScenarioTemplate,
    SessionSummary,
)
from backend.services.expert_team.orchestrator import DebateOrchestrator
from hermes_agent.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


async def _resolve_ticker_from_question(question: str) -> Optional[str]:
    """参考 Research 流程：未绑定标的时，从问题文本解析出标准 ticker 编码，
    供后续个股数据采集使用（quote/fundamental/technicals）。

    关键设计（get_search_quote 是联想搜索，非精确查单个代码）：
      1. 若问题含**标准代码**（US.AAPL / 00700.HK / AAPL / 00700）→ 直接 format_ticker
         标准化，不经过 search_quote（避免联想搜索返回多个相关标的导致误匹配）。
      2. 仅当是**中文名/非标输入**时才走 Futu SEARCH_QUOTE 联想，并精确筛选候选：
         优先选 sec_type=STOCK 且名称匹配的标的，而非盲目取第一个候选。
    """
    import re

    if not question:
        return None
    from backend.core.ticker_format import format_ticker

    # 1) 显式标准代码 → 直接标准化，不查联想
    # 覆盖: US.AAPL / HK.00700 / HK.0772 / 00700.HK / AAPL / 00700
    m_code = re.search(
        r"(?:US\.|HK\.)[A-Za-z0-9]{1,5}"
        r"|\d{4,5}\.HK"
        r"|\b[A-Za-z]{1,5}(?:\.[A-Z]{2})?\b",
        question,
    )
    if m_code:
        raw = m_code.group(0).strip()
        if raw:
            try:
                return format_ticker(raw)
            except Exception:  # noqa: BLE001
                return raw

    # 2) 中文股票名：剔除常见动词/语气词后，取第一个中文片段
    _STOP = (
        "研究",
        "分析",
        "请问",
        "如何",
        "怎样",
        "怎么样",
        "怎么",
        "看待",
        "当前",
        "最新",
        "走势",
        "行情",
        "价格",
        "建议",
        "评估",
        "评价",
        "研判",
        "投研",
        "基本面",
        "技术面",
        "深度",
        "可以",
        "给我",
        "看看",
        "关注",
        "看好",
        "能否",
        "是否",
        "市场",
        "股票",
        "未来",
        "一下",
        "一个",
        "这家",
        "那只",
        "现在",
        "最近",
        "对",
        "关于",
        "以及",
        "和",
        "吗",
        "呢",
    )
    _clean = question
    for w in sorted(_STOP, key=len, reverse=True):
        _clean = re.sub(w, "", _clean)
    _frag = re.search(r"[\u4e00-\u9fa5]{2,6}", _clean)
    keyword = None
    if _frag:
        _kw = _frag.group(0)
        for w in ("吗", "呢", "怎么样", "怎么"):
            if _kw.endswith(w):
                _kw = _kw[: -len(w)]
                break
        keyword = _kw if len(_kw) >= 2 else None
    if not keyword:
        return None

    # 3) 中文名 → 统一模糊匹配（复用 /market/search 级联：本地词库 → Futu SEARCH_QUOTE）
    #    精确筛选候选（优先 STOCK 类型，其次名称匹配）
    try:
        # 注意: search_quote 在 DataServiceFacade(data_service) 上，不在 MarketDataService(market_data_service)
        from backend.services.datasource.business import data_service
        from backend.services.fund_flow.ticker import ticker_service

        candidates: list[dict] = []
        local = await ticker_service.search_tickers(keyword)
        # 本地词库命中（无论 success/error，只要 data 非空即采用）
        if local.get("data"):
            candidates = local["data"]
        # 兜底降级：本地词库未覆盖该标的（data 为空，含 success 空结果或异常）时，
        # 主动走 Futu SEARCH_QUOTE 实时联想，避免词库不全导致解析失败（如港股小票）。
        if not candidates:
            try:
                res = await data_service.search_quote(keyword=keyword, max_count=10)
                if res.is_success and res.data:
                    candidates = res.data if isinstance(res.data, list) else []
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[expert-team] Futu search_quote 降级失败 ({keyword}): {e}")
        if not candidates:
            return None
        # 优先 STOCK 类型
        for c in candidates:
            if str(c.get("sec_type") or c.get("type") or "").upper() == "STOCK":
                code = c.get("code") or c.get("symbol") or c.get("ticker")
                if code:
                    return format_ticker(code)
        # 无 STOCK 时，取名称含 keyword 的候选（如中文名联想）
        for c in candidates:
            name = str(c.get("name", ""))
            if name and keyword in name:
                code = c.get("code") or c.get("symbol") or c.get("ticker")
                if code:
                    return format_ticker(code)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[expert-team] 问题文本解析 ticker 失败: {e}")
    return None


# ─── 双层持久化配置 ─────────────────────────────────────────────
REDIS_KEY_PREFIX = "quant:expert_team:"
REDIS_TTL = 12 * 3600  # 12 小时

# 内存兜底 (Redis/PG 均不可用时保证本地可跑)
_memory_sessions: dict[str, DebateSession] = {}


class ExpertTeamService:
    """专家团服务 (Redis 热 + PG 冷双层持久化)"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.orchestrator = DebateOrchestrator(tool_registry=tool_registry)
        # 追踪后台 PG 落盘任务，避免事件循环关闭时任务悬挂触发
        # "Task was destroyed but it is pending" 告警 / The operation was canceled
        self._pg_tasks: set[asyncio.Task] = set()

    async def analyze_stream(self, request: AnalyzeRequest) -> AsyncGenerator[str, None]:
        """
        执行专家团分析，返回 SSE 格式事件流。
        辩论完成后自动持久化会话至 Redis + PG。
        """
        final_session: Optional[DebateSession] = None

        # 未绑定标的时，参考 Research 流程：从问题文本解析 ticker（Futu SEARCH_QUOTE）
        resolved_ticker = request.ticker
        if not resolved_ticker:
            resolved_ticker = await _resolve_ticker_from_question(request.question)
            if resolved_ticker and resolved_ticker != request.ticker:
                logger.info(f"[expert-team] 从问题解析出标的: {request.question[:30]} -> {resolved_ticker}")

        async for event in self.orchestrator.run_debate_stream(
            scenario_id=request.scenario,
            question=request.question,
            ticker=resolved_ticker,
            code_context=request.code_context,
            extra_context=request.extra_context,
            rounds=request.rounds,
            expert_ids=request.expert_ids,
        ):
            # 拦截 done 事件提取 session_id
            if event.type == "done":
                final_session = self.orchestrator._last_session
            payload = event.model_dump()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # 辩论结束后异步持久化
        if final_session:
            await self.save_session(final_session)

    def get_scenarios(self) -> list[ScenarioTemplate]:
        """获取所有可用场景模板"""
        return list_scenarios()

    async def get_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """获取历史会话列表 (Redis 热 → PG 冷 → 内存兜底)"""
        sessions: list[DebateSession] = []

        # ─── Layer 1: Redis SCAN ───
        # 外层 wait_for 超时保护：Redis 不可达时连接可能无限挂起，
        # 必须有超时才能快速降级，否则会阻塞事件循环（测试/生产均受影响）
        try:
            from backend.core.redis_client import redis_client

            cursor = 0
            while True:
                cursor, keys = await asyncio.wait_for(
                    redis_client.scan(cursor=cursor, match=f"{REDIS_KEY_PREFIX}*", count=100),
                    timeout=2.0,
                )
                for key in keys:
                    raw = await asyncio.wait_for(redis_client.get(key), timeout=2.0)
                    if raw:
                        sessions.append(DebateSession(**json.loads(raw)))
                if cursor == 0:
                    break

            if sessions:
                return self._to_summaries(sessions, limit)
        except Exception as e:
            logger.debug(f"[ExpertTeam] Redis SCAN 失败，降级: {e}")

        # ─── Layer 2: PostgreSQL ───
        try:

            def fetch_pg():
                from backend.core.database import SessionLocal
                from backend.core.models import ExpertTeamSession

                with SessionLocal() as db:
                    rows = db.query(ExpertTeamSession).order_by(ExpertTeamSession.created_at.desc()).limit(limit).all()
                    return [r.session_data for r in rows]

            pg_data = await asyncio.wait_for(asyncio.to_thread(fetch_pg), timeout=2.0)
            for data in pg_data:
                sessions.append(DebateSession(**data))
            if sessions:
                return self._to_summaries(sessions, limit)
        except Exception as e:
            logger.debug(f"[ExpertTeam] PG 查询失败，降级: {e}")

        # ─── Layer 3: 内存兜底 ───
        return self._to_summaries(list(_memory_sessions.values()), limit)

    async def get_session(self, session_id: str) -> Optional[DebateSession]:
        """获取完整辩论记录 (Redis → PG → 内存)"""
        # Layer 1: Redis
        try:
            from backend.core.redis_client import redis_client

            raw = await asyncio.wait_for(
                redis_client.get(f"{REDIS_KEY_PREFIX}{session_id}"),
                timeout=2.0,
            )
            if raw:
                return DebateSession(**json.loads(raw))
        except Exception as e:
            logger.debug(f"[ExpertTeam] Redis GET 失败: {e}")

        # Layer 2: PostgreSQL
        try:

            def fetch_pg():
                from backend.core.database import SessionLocal
                from backend.core.models import ExpertTeamSession

                with SessionLocal() as db:
                    row = db.query(ExpertTeamSession).filter(ExpertTeamSession.session_id == session_id).first()
                    return row.session_data if row else None

            pg_data = await asyncio.wait_for(asyncio.to_thread(fetch_pg), timeout=2.0)
            if pg_data:
                session = DebateSession(**pg_data)
                # 回温至 Redis
                asyncio.create_task(self._redis_set(session))
                return session
        except Exception as e:
            logger.debug(f"[ExpertTeam] PG GET 失败: {e}")

        # Layer 3: 内存
        return _memory_sessions.get(session_id)

    async def delete_session(self, session_id: str) -> bool:
        """删除历史会话（Redis 热 + PG 冷 + 内存兜底），返回是否删除成功。"""
        deleted = False
        # Layer 1: Redis
        try:
            from backend.core.redis_client import redis_client

            removed = await asyncio.wait_for(
                redis_client.delete(f"{REDIS_KEY_PREFIX}{session_id}"),
                timeout=2.0,
            )
            if removed:
                deleted = True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ExpertTeam] Redis DELETE 失败: {e}")

        # Layer 2: PostgreSQL
        try:

            def del_pg():
                from backend.core.database import SessionLocal
                from backend.core.models import ExpertTeamSession

                with SessionLocal() as db:
                    row = db.query(ExpertTeamSession).filter(ExpertTeamSession.session_id == session_id).first()
                    if row:
                        db.delete(row)
                        db.commit()
                        return True
                    return False

            try:
                pg_del = await asyncio.wait_for(asyncio.to_thread(del_pg), timeout=2.0)
            except Exception:  # noqa: BLE001
                pg_del = False
            if pg_del:
                deleted = True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[ExpertTeam] PG DELETE 失败: {e}")

        # Layer 3: 内存兜底
        if _memory_sessions.pop(session_id, None) is not None:
            deleted = True

        return deleted

    async def save_session(self, session: DebateSession) -> None:
        """保存会话: Redis 热 + 异步 PG 冷 + 内存兜底"""
        # Layer 3: 内存始终写入 (本地降级兜底)
        _memory_sessions[session.session_id] = session

        # Layer 1: Redis
        await self._redis_set(session)

        # Layer 2: 异步 PG 落盘 (不阻塞 SSE 流)
        task = asyncio.create_task(self._pg_upsert(session))
        self._pg_tasks.add(task)
        task.add_done_callback(self._pg_tasks.discard)

    # ─── 内部持久化原语 ─────────────────────────────────────────

    async def _redis_set(self, session: DebateSession) -> None:
        """写入 Redis 热缓存"""
        try:
            from backend.core.redis_client import redis_client

            await asyncio.wait_for(
                redis_client.set(
                    f"{REDIS_KEY_PREFIX}{session.session_id}",
                    session.model_dump_json(),
                    ex=REDIS_TTL,
                ),
                timeout=2.0,
            )
        except Exception as e:
            logger.warning(f"[ExpertTeam] Redis 写入失败: {e}")

    async def _pg_upsert(self, session: DebateSession) -> None:
        """异步 PG upsert (由 create_task 调度)"""
        try:

            def upsert():
                from backend.core.database import SessionLocal
                from backend.core.models import ExpertTeamSession

                with SessionLocal() as db:
                    existing = (
                        db.query(ExpertTeamSession).filter(ExpertTeamSession.session_id == session.session_id).first()
                    )
                    data = session.model_dump()
                    if existing:
                        existing.session_data = data
                    else:
                        db.add(ExpertTeamSession(session_id=session.session_id, session_data=data))
                    db.commit()

            # 超时保护：避免 PG 不可达时任务无限悬挂（测试/loop 关闭时泄漏）
            await asyncio.wait_for(asyncio.to_thread(upsert), timeout=5.0)
        except asyncio.CancelledError:
            # 事件循环关闭时任务被取消，静默返回，避免 "Task was destroyed" 告警
            return
        except Exception as e:
            logger.warning(f"[ExpertTeam] PG 写入失败: {e}")

    # ─── 辅助 ──────────────────────────────────────────────────

    @staticmethod
    def _to_summaries(sessions: list[DebateSession], limit: int) -> list[SessionSummary]:
        """将 DebateSession 列表转为 SessionSummary 列表"""
        sorted_sessions = sorted(sessions, key=lambda s: s.created_at, reverse=True)[:limit]
        return [
            SessionSummary(
                session_id=s.session_id,
                scenario=s.scenario,
                question=s.question,
                status=s.status,
                expert_count=len(s.experts),
                probability_assessment=(s.chief_report.probability_assessment if s.chief_report else None),
                created_at=s.created_at,
                completed_at=s.completed_at,
            )
            for s in sorted_sessions
        ]


# 全局单例 (延迟初始化 tool_registry)
_service_instance: Optional[ExpertTeamService] = None


def get_expert_team_service(tool_registry: Optional[ToolRegistry] = None) -> ExpertTeamService:
    """获取专家团服务单例

    tool_registry 兜底：若调用方未显式传入，则尝试从全局生命周期注入的
    global_registry 获取（App 启动时构建），确保共享数据采集能真正调用工具，
    避免所有数据项因 registry=None 被 skip 为"工具不可用"。
    """
    global _service_instance
    resolved = tool_registry
    if resolved is None:
        try:
            from backend.bootstrap.lifecycle import global_registry

            resolved = global_registry
        except Exception:  # noqa: BLE001
            resolved = None
    if _service_instance is None:
        _service_instance = ExpertTeamService(tool_registry=resolved)
    elif resolved and _service_instance.orchestrator.tool_registry is None:
        _service_instance.orchestrator.tool_registry = resolved
    return _service_instance
