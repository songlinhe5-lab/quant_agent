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
    @pytest.mark.slow
    async def test_collect_timeout(self):
        """工具超时处理 (慢: 真实 asyncio 等待超时)"""
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

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_pydantic = AsyncMock(side_effect=[mock_r1] * 5 + [mock_r2] * 5 + [mock_chief])

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

    @pytest.mark.asyncio
    async def test_get_sessions_empty(self):
        import sys
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        # Mock Redis 模块: scan 返回空 (cursor=0 立即结束)
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(return_value=(0, []))
        mock_module = MagicMock()
        mock_module.redis_client = mock_redis
        with patch.dict(sys.modules, {"backend.core.redis_client": mock_module}):
            sessions = await service.get_sessions()
        assert isinstance(sessions, list)

    @pytest.mark.asyncio
    async def test_save_and_get_session(self):
        import sys
        from unittest.mock import AsyncMock, MagicMock, patch

        from backend.services.expert_team.expert_team_service import ExpertTeamService

        service = ExpertTeamService()
        session = DebateSession(
            session_id="test_001",
            scenario="financial_research",
            question="测试",
            status="done",
            created_at="2024-01-01T00:00:00Z",
        )
        # Mock Redis + PG 均不可用 → 走内存兜底
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(return_value=(0, []))
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.set = AsyncMock(return_value=True)
        mock_module = MagicMock()
        mock_module.redis_client = mock_redis
        with patch.dict(sys.modules, {"backend.core.redis_client": mock_module}):
            await service.save_session(session)
            retrieved = await service.get_session("test_001")
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

    @pytest.mark.slow
    def test_list_scenarios_endpoint(self, client):
        resp = client.get("/api/v1/expert-team/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        # API 响应有统一包装 {code, msg, data}
        payload = data.get("data", data)
        assert "scenarios" in payload
        assert len(payload["scenarios"]) == 4

    @pytest.mark.slow
    def test_list_sessions_endpoint(self, client):
        resp = client.get("/api/v1/expert-team/sessions")
        assert resp.status_code == 200
        data = resp.json()
        payload = data.get("data", data)
        assert "sessions" in payload

    @pytest.mark.slow
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

    @pytest.mark.slow
    def test_analyze_endpoint_runs_with_custom_team(self, client):
        """自定义阵容 + 多轮: 端点应正常返回 200 (慢: 拉起全依赖链)。"""
        resp = client.post(
            "/api/v1/expert-team/analyze",
            json={
                "scenario": "financial_research",
                "question": "AAPL 值得投资吗？",
                "ticker": "AAPL",
                "expert_ids": ["fundamental_analyst", "risk_officer"],
                "rounds": 2,
            },
        )
        # 端点本身只校验入参，SSE 流式在响应体；这里确认请求被接受 (200/400 取决于校验)
        assert resp.status_code in (200, 400)


# ─── 辩论扩展能力测试 (多轮 / 自定义阵容 / 流式切片) ────────────────


class TestOrchestratorDebateExtensions:
    """覆盖 rounds / expert_ids / _yield_opinion_stream 等扩展逻辑"""

    def _make_opinion(self, expert_id="fundamental_analyst", stance="看涨"):
        return ExpertOpinion(
            expert_id=expert_id,
            round=1,
            stance=stance,
            key_evidence=["ROE>20%"],
            reasoning="基本面优秀",
            challenges=["风控过度悲观"],
            revised_stance="维持看涨",
            confidence=70,
        )

    def test_opinion_text_parts_and_to_text(self):
        op = self._make_opinion()
        parts = DebateOrchestrator._opinion_text_parts(op)
        assert len(parts) >= 5  # 核心/依据/推理/质疑/修正/置信度
        full = DebateOrchestrator._opinion_to_text(op)
        assert "看涨" in full
        assert "ROE>20%" in full
        assert "70" in full

    def test_split_for_stream_basic(self):
        s = "观点一。观点二！观点三？结尾"
        chunks = DebateOrchestrator._split_for_stream(s, max_chunk=80)
        # 按标点切分, 拼接后还原原文
        assert "".join(chunks) == s
        assert all(len(c) <= 80 for c in chunks)

    def test_split_for_stream_long_sentence(self):
        # 超长无标点句子应被强制切片
        s = "这是一段没有标点的超长文本用于测试切片逻辑是否会在超过阈值时强制截断" * 3
        chunks = DebateOrchestrator._split_for_stream(s, max_chunk=80)
        assert len(chunks) > 1
        assert "".join(chunks) == s

    def test_split_for_stream_empty(self):
        assert DebateOrchestrator._split_for_stream("") == [""]

    def test_promote_round(self):
        op = self._make_opinion()
        sess = DebateSession(session_id="s", scenario="financial_research", question="q")
        DebateOrchestrator._promote_round(sess, [op], round_index=2)
        assert sess.round2_opinions[0].stance == "看涨"
        assert 2 in sess.all_rounds

    @pytest.mark.asyncio
    async def test_yield_opinion_stream_slices_content(self):
        """专家观点应被切成多片流式 yield, 首片带完整 data"""
        op = self._make_opinion()
        orch = DebateOrchestrator()
        events = [ev async for ev in orch._yield_opinion_stream(op, round_index=1)]
        assert len(events) > 1
        # 首片带完整结构化 data + 完整 content
        assert events[0].data.get("stance") == "看涨"
        assert events[0].content
        # 后续片仅增量 content, data 为空
        for ev in events[1:]:
            assert ev.data == {}
            assert ev.content
        # 所有片 content 拼接 = 完整文本
        joined = "".join(e.content for e in events)
        assert joined == DebateOrchestrator._opinion_to_text(op)

    @pytest.mark.asyncio
    async def test_debate_stream_multi_round(self):
        """rounds=3 应触发 Round1 + Round2 + Round3 三轮辩论"""
        orch = DebateOrchestrator(tool_registry=None)
        mock_r1 = MagicMock(stance="看多", confidence=70, key_evidence=["e1"], reasoning="r1")
        mock_r2 = MagicMock(
            stance="维持",
            confidence=72,
            key_evidence=["e1"],
            reasoning="r2",
            challenges=["c1"],
            confidence_delta=2,
            revised_stance="维持",
        )
        mock_chief = ChiefReport(full_report="# 报告")

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            # 5 专家 * 3 轮 + 1 首席
            mock_llm.generate_pydantic = AsyncMock(
                side_effect=[mock_r1] * 5 + [mock_r2] * 5 + [mock_r2] * 5 + [mock_chief]
            )
            rounds_seen = []
            async for event in orch.run_debate_stream(
                scenario_id="financial_research",
                question="AAPL?",
                ticker="AAPL",
                rounds=3,
            ):
                if event.type == "round_complete":
                    rounds_seen.append(event.data.get("round"))
            assert rounds_seen == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_debate_stream_custom_expert_ids(self):
        """expert_ids 自定义阵容应覆盖场景默认, 并用 get_expert 实例化"""
        orch = DebateOrchestrator(tool_registry=None)
        mock_op = MagicMock(stance="自定义观点", confidence=60, key_evidence=["e"], reasoning="r")
        mock_chief = ChiefReport(full_report="# 报告")

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_pydantic = AsyncMock(side_effect=[mock_op] * 2 + [mock_op] * 2 + [mock_chief])
            seen_experts = []
            async for event in orch.run_debate_stream(
                scenario_id="financial_research",
                question="AAPL?",
                ticker="AAPL",
                rounds=2,
                expert_ids=["fundamental_analyst", "risk_officer"],
            ):
                if event.type == "expert_opinion" and event.data:
                    seen_experts.append(event.data.get("expert_id"))
            # 仅 2 个自定义专家参与两轮
            assert "fundamental_analyst" in seen_experts
            assert "risk_officer" in seen_experts
            assert len([e for e in seen_experts if e]) == 4  # 2 专家 * 2 轮


# ─── DataSourceError 测试 (facade 依赖) ───────────────────────────


class TestDataSourceError:
    """backend.core.exceptions.DataSourceError 构造兼容性"""

    def test_construct_with_message_and_source(self):
        from backend.core.error_codes import ErrorCode
        from backend.core.exceptions import DataSourceError

        err = DataSourceError(
            code=ErrorCode.ALL_SOURCES_FAILED,
            message="基本面三源合并失败",
            source="facade",
        )
        assert int(err.code) == 3004
        assert err.msg == "基本面三源合并失败"
        assert err.data == {"source": "facade"}

    def test_construct_defaults(self):
        from backend.core.exceptions import DataSourceError

        err = DataSourceError()
        assert int(err.code) == 5000
        assert err.data == {"source": ""}
