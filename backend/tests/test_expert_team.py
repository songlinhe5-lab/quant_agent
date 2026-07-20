"""
专家团系统单元测试 + 集成测试
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.expert_team.data_collector import (
    collect_shared_data,
    format_shared_data_for_prompt,
)
from backend.services.expert_team.expert_registry import (
    EXPERT_REGISTRY,
    SCENARIO_TEMPLATES,
    get_expert,
    get_scenario,
    instantiate_expert_team,
    list_scenarios,
)
from backend.services.expert_team.models import (
    AnalyzeRequest,
    ChiefReport,
    DebateSession,
    ExpertOpinion,
    ExpertRole,
    ScenarioTemplate,
    SessionSummary,
    StreamEvent,
)
from backend.services.expert_team.orchestrator import DebateOrchestrator


# ─── models.py 测试 ────────────────────────────────────────────


class TestModels:
    """数据模型测试"""

    def test_expert_role_creation(self):
        expert = ExpertRole(
            id="test_analyst",
            name="测试分析师",
            domain="finance",
            bias="bullish",
            available_tools=["tool_a"],
        )
        assert expert.id == "test_analyst"
        assert expert.domain == "finance"
        assert expert.bias == "bullish"
        assert expert.system_prompt == ""

    def test_expert_opinion_confidence_bounds(self):
        opinion = ExpertOpinion(
            expert_id="test",
            round=1,
            stance="测试观点",
            confidence=75,
        )
        assert opinion.confidence == 75
        assert opinion.challenges == []
        assert opinion.confidence_delta == 0

    def test_expert_opinion_confidence_validation(self):
        with pytest.raises(Exception):
            ExpertOpinion(
                expert_id="test",
                round=1,
                stance="测试",
                confidence=150,  # 超出范围
            )

    def test_chief_report_defaults(self):
        report = ChiefReport()
        assert report.probability_assessment == 50
        assert report.consensus_areas == []
        assert report.full_report == ""

    def test_debate_session_status(self):
        session = DebateSession(
            session_id="abc123",
            scenario="financial_research",
            question="测试问题",
        )
        assert session.status == "pending"
        assert session.round1_opinions == []
        assert session.chief_report is None

    def test_scenario_template(self):
        template = ScenarioTemplate(
            id="test_scenario",
            name="测试场景",
            domain="finance",
            expert_ids=["a", "b"],
            data_requirements=["quote"],
        )
        assert len(template.expert_ids) == 2
        assert template.chief_prompt_file == "chief_analyst.md"

    def test_analyze_request(self):
        req = AnalyzeRequest(
            scenario="financial_research",
            question="AAPL 值得投资吗？",
            ticker="AAPL",
        )
        assert req.ticker == "AAPL"
        assert req.code_context is None

    def test_stream_event_types(self):
        event = StreamEvent(type="status", message="测试")
        assert event.type == "status"
        assert event.data == {}


# ─── expert_registry.py 测试 ───────────────────────────────────


class TestExpertRegistry:
    """专家注册表测试"""

    def test_registry_has_all_experts(self):
        assert len(EXPERT_REGISTRY) == 17
        # 金融域 13 个
        finance_experts = [e for e in EXPERT_REGISTRY.values() if e.domain == "finance"]
        assert len(finance_experts) == 13
        # 代码域 4 个
        code_experts = [e for e in EXPERT_REGISTRY.values() if e.domain == "code"]
        assert len(code_experts) == 4

    def test_get_expert_valid(self):
        expert = get_expert("fundamental_analyst")
        assert expert.name == "基本面分析师"
        assert expert.domain == "finance"

    def test_get_expert_invalid(self):
        with pytest.raises(ValueError, match="未知专家"):
            get_expert("nonexistent_expert")

    def test_get_scenario_valid(self):
        scenario = get_scenario("financial_research")
        assert scenario.name == "金融投研"
        assert len(scenario.expert_ids) == 5

    def test_get_scenario_invalid(self):
        with pytest.raises(ValueError, match="未知场景"):
            get_scenario("nonexistent")

    def test_list_scenarios(self):
        scenarios = list_scenarios()
        assert len(scenarios) == 4
        ids = [s.id for s in scenarios]
        assert "financial_research" in ids
        assert "code_review" in ids
        assert "full_investment" in ids
        assert "trading_decision" in ids

    def test_instantiate_expert_team_finance(self):
        team = instantiate_expert_team("financial_research")
        assert len(team) == 5
        ids = [e.id for e in team]
        assert "fundamental_analyst" in ids
        assert "risk_officer" in ids

    def test_instantiate_expert_team_code(self):
        team = instantiate_expert_team("code_review")
        assert len(team) == 4
        ids = [e.id for e in team]
        assert "code_architect" in ids
        assert "security_expert" in ids

    def test_instantiate_full_investment_team(self):
        team = instantiate_expert_team("full_investment")
        assert len(team) == 11
        ids = [e.id for e in team]
        assert "chief_investment_officer" in ids
        assert "trade_executor" in ids
        assert "portfolio_risk_manager" in ids
        assert "news_analyst" in ids

    def test_instantiate_trading_decision_team(self):
        team = instantiate_expert_team("trading_decision")
        assert len(team) == 5
        ids = [e.id for e in team]
        assert "trade_executor" in ids
        assert "sentiment_analyst" in ids

    def test_risk_officer_bearish_bias(self):
        expert = get_expert("risk_officer")
        assert expert.bias == "bearish"

    def test_portfolio_risk_manager_bearish_bias(self):
        expert = get_expert("portfolio_risk_manager")
        assert expert.bias == "bearish"

    def test_expert_prompt_loading(self):
        """验证 prompt 文件可以被加载"""
        expert = get_expert("fundamental_analyst")
        # prompt 文件存在时应加载成功
        assert "基本面" in expert.system_prompt or expert.system_prompt == ""


# ─── data_collector.py 测试 ────────────────────────────────────


class TestDataCollector:
    """数据采集器测试"""

    @pytest.mark.asyncio
    async def test_collect_code_context(self):
        """code_context 直接从参数获取"""
        result = await collect_shared_data(
            data_requirements=["code_context"],
            code_context="def hello(): pass",
        )
        assert result["code_context"] == "def hello(): pass"

    @pytest.mark.asyncio
    async def test_collect_unknown_type(self):
        """未知数据类型应跳过"""
        result = await collect_shared_data(
            data_requirements=["unknown_type"],
        )
        assert result["unknown_type"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_collect_no_registry(self):
        """无 ToolRegistry 时应跳过工具采集"""
        result = await collect_shared_data(
            data_requirements=["quote"],
            tool_registry=None,
            ticker="AAPL",
        )
        assert result["quote"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_collect_with_mock_registry(self):
        """Mock ToolRegistry 正常采集"""
        mock_registry = MagicMock()
        mock_registry.execute = AsyncMock(return_value={"price": 150.0})

        result = await collect_shared_data(
            data_requirements=["quote"],
            tool_registry=mock_registry,
            ticker="AAPL",
        )
        assert result["quote"] == {"price": 150.0}
        mock_registry.execute.assert_called_once_with("get_broker_market_data", ticker="AAPL")

    @pytest.mark.asyncio
    async def test_collect_timeout(self):
        """工具超时处理"""
        mock_registry = MagicMock()

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(100)

        mock_registry.execute = slow_execute

        # 临时缩短超时
        import backend.services.expert_team.data_collector as dc
        original_timeout = dc._COLLECT_TIMEOUT
        dc._COLLECT_TIMEOUT = 0.1

        try:
            result = await collect_shared_data(
                data_requirements=["quote"],
                tool_registry=mock_registry,
                ticker="AAPL",
            )
            assert result["quote"]["status"] == "timeout"
        finally:
            dc._COLLECT_TIMEOUT = original_timeout

    def test_format_shared_data(self):
        """数据格式化"""
        data = {
            "quote": {"price": 150.0, "change": "+2.5%"},
            "fundamental": {"status": "error", "message": "API 超时"},
            "code_context": "def test(): pass",
        }
        text = format_shared_data_for_prompt(data)
        assert "quote" in text
        assert "150.0" in text
        assert "数据不可用" in text
        assert "def test(): pass" in text

    def test_format_shared_data_truncation(self):
        """超长数据截断"""
        data = {"big_data": "x" * 5000}
        text = format_shared_data_for_prompt(data, max_chars=1000)
        assert "截断" in text or "省略" in text


# ─── orchestrator.py 测试 ──────────────────────────────────────


class TestOrchestrator:
    """编排引擎测试"""

    @pytest.mark.asyncio
    async def test_debate_stream_events(self):
        """完整辩论流应产生正确的事件序列"""
        orchestrator = DebateOrchestrator(tool_registry=None)

        # Mock LLM 调用
        mock_r1 = MagicMock()
        mock_r1.stance = "看多"
        mock_r1.confidence = 70
        mock_r1.key_evidence = ["ROE 持续 >20%"]
        mock_r1.reasoning = "基本面优秀"

        mock_r2 = MagicMock()
        mock_r2.stance = "维持看多"
        mock_r2.confidence = 72
        mock_r2.key_evidence = ["ROE 持续 >20%"]
        mock_r2.reasoning = "辩论后维持"
        mock_r2.challenges = ["风控官过度悲观"]
        mock_r2.confidence_delta = 2
        mock_r2.revised_stance = "维持看多"

        mock_chief = ChiefReport(
            consensus_areas=["基本面优秀"],
            divergence_areas=["短期估值"],
            strongest_bull_case="ROE >20%",
            strongest_bear_case="估值偏高",
            probability_assessment=65,
            final_recommendation="逢低买入",
            risk_warnings=["估值回调风险"],
            minority_opinion="风控官建议观望",
            full_report="# 报告\n测试",
        )

        with patch(
            "backend.services.expert_team.orchestrator.llm_service"
        ) as mock_llm:
            mock_llm.generate_pydantic = AsyncMock(
                side_effect=[mock_r1] * 5 + [mock_r2] * 5 + [mock_chief]
            )

            events = []
            async for event in orchestrator.run_debate_stream(
                scenario_id="financial_research",
                question="AAPL 值得投资吗？",
                ticker="AAPL",
            ):
                events.append(event)

        # 验证事件序列
        event_types = [e.type for e in events]
        assert "status" in event_types
        assert "expert_opinion" in event_types
        assert "round_complete" in event_types
        assert "chief_report" in event_types
        assert "done" in event_types

        # 最后一个事件应该是 done
        assert events[-1].type == "done"

    @pytest.mark.asyncio
    async def test_debate_invalid_scenario(self):
        """无效场景应产生 error 事件"""
        orchestrator = DebateOrchestrator()

        events = []
        async for event in orchestrator.run_debate_stream(
            scenario_id="invalid_scenario",
            question="test",
        ):
            events.append(event)

        assert any(e.type == "error" for e in events)


# ─── expert_team_service.py 测试 ───────────────────────────────


class TestExpertTeamService:
    """服务层测试"""

    def test_get_scenarios(self):
        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        scenarios = service.get_scenarios()
        assert len(scenarios) == 4

    def test_get_sessions_empty(self):
        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        sessions = service.get_sessions()
        assert isinstance(sessions, list)

    def test_save_and_get_session(self):
        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        session = DebateSession(
            session_id="test_001",
            scenario="financial_research",
            question="测试",
            status="done",
            created_at="2024-01-01T00:00:00Z",
        )
        service.save_session(session)
        retrieved = service.get_session("test_001")
        assert retrieved is not None
        assert retrieved.question == "测试"

    @pytest.mark.asyncio
    async def test_analyze_stream_sse_format(self):
        """SSE 输出格式验证"""
        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        request = AnalyzeRequest(
            scenario="financial_research",
            question="测试",
            ticker="AAPL",
        )

        # Mock orchestrator
        async def mock_stream(*args, **kwargs):
            yield StreamEvent(type="status", message="测试事件")
            yield StreamEvent(type="done", message="完成")

        service.orchestrator.run_debate_stream = mock_stream

        chunks = []
        async for chunk in service.analyze_stream(request):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].startswith("data: ")
        assert chunks[0].endswith("\n\n")
        # 验证 JSON 可解析
        payload = json.loads(chunks[0].replace("data: ", "").strip())
        assert payload["type"] == "status"


# ─── routers/expert_team.py 集成测试 ───────────────────────────


class TestExpertTeamRouter:
    """API 端点集成测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app)

    def test_list_scenarios_endpoint(self, client):
        resp = client.get("/api/v1/expert-team/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        # API 响应有统一包装 {code, msg, data}
        payload = data.get("data", data)
        assert "scenarios" in payload
        assert len(payload["scenarios"]) == 4

    def test_list_sessions_endpoint(self, client):
        resp = client.get("/api/v1/expert-team/sessions")
        assert resp.status_code == 200
        data = resp.json()
        payload = data.get("data", data)
        assert "sessions" in payload

    def test_get_session_not_found(self, client):
        resp = client.get("/api/v1/expert-team/sessions/nonexistent")
        assert resp.status_code == 404

    def test_analyze_invalid_scenario(self, client):
        resp = client.post(
            "/api/v1/expert-team/analyze",
            json={
                "scenario": "invalid",
                "question": "test",
            },
        )
        assert resp.status_code == 400
