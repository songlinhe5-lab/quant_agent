"""
专家团对外统一入口
封装 Orchestrator，提供会话管理 + 历史查询
"""

import json
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

# 内存会话存储 (后续可迁移至 Redis)
_sessions: dict[str, DebateSession] = {}


class ExpertTeamService:
    """专家团服务"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.orchestrator = DebateOrchestrator(tool_registry=tool_registry)

    async def analyze_stream(self, request: AnalyzeRequest) -> AsyncGenerator[str, None]:
        """
        执行专家团分析，返回 SSE 格式事件流。

        Yields:
            str: SSE 格式文本 "data: {...}\n\n"
        """
        async for event in self.orchestrator.run_debate_stream(
            scenario_id=request.scenario,
            question=request.question,
            ticker=request.ticker,
            code_context=request.code_context,
            extra_context=request.extra_context,
        ):
            # 序列化为 SSE
            payload = event.model_dump()
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        # 存储会话 (简化: 仅存最终状态)
        # 注意: 完整 session 在 orchestrator 内部管理，此处仅做索引

    def get_scenarios(self) -> list[ScenarioTemplate]:
        """获取所有可用场景模板"""
        return list_scenarios()

    def get_sessions(self, limit: int = 20) -> list[SessionSummary]:
        """获取历史会话列表"""
        sessions = sorted(
            _sessions.values(),
            key=lambda s: s.created_at,
            reverse=True,
        )[:limit]

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
            for s in sessions
        ]

    def get_session(self, session_id: str) -> Optional[DebateSession]:
        """获取完整辩论记录"""
        return _sessions.get(session_id)

    def save_session(self, session: DebateSession) -> None:
        """保存会话"""
        _sessions[session.session_id] = session


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
