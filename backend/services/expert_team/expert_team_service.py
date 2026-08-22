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

        async for event in self.orchestrator.run_debate_stream(
            scenario_id=request.scenario,
            question=request.question,
            ticker=request.ticker,
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
    """获取专家团服务单例"""
    global _service_instance
    if _service_instance is None:
        _service_instance = ExpertTeamService(tool_registry=tool_registry)
    elif tool_registry and _service_instance.orchestrator.tool_registry is None:
        _service_instance.orchestrator.tool_registry = tool_registry
    return _service_instance
