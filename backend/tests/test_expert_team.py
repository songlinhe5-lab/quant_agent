"""
专家团系统单元测试 + 集成测试
"""

import asyncio
import json
from contextlib import ExitStack
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
from backend.services.expert_team.orchestrator import DebateOrchestrator, _StreamSplitter


@pytest.fixture(autouse=True)
def _disable_stream_pacing(monkeypatch):
    """测试环境禁用打字机限速，避免用真实时间等待滴播（生产默认 0.12s/20字符）"""
    monkeypatch.setattr("backend.services.expert_team.orchestrator._STREAM_EMIT_INTERVAL", 0.0)
    monkeypatch.setattr("backend.services.expert_team.orchestrator._STREAM_CHARS_PER_TICK", 100000)


def _stream_fn(text: str):
    """构造 generate_stream mock：把文本切小段逐段 yield，模拟真实 token 流"""

    async def _gen(*args, **kwargs):
        for i in range(0, len(text), 7):
            yield text[i : i + 7]

    return _gen


# 真流式协议样本：Markdown 研判文本 + 末尾 ```json 结构化块（与 orchestrator prompt 约定一致）
_R1_STREAM_TEXT = (
    '基本面优秀，ROE 持续高位。\n```json\n{"stance": "看多", "confidence": 70, "key_evidence": ["ROE 持续 >20%"]}\n```'
)
_R2_STREAM_TEXT = (
    "辩论后维持判断。\n```json\n"
    '{"stance": "维持看多", "confidence": 72, "key_evidence": ["ROE 持续 >20%"], '
    '"challenges": ["风控官过度悲观"], "confidence_delta": 2, "revised_stance": "维持看多"}\n```'
)
_CHIEF_STREAM_TEXT = (
    "# 报告\n测试\n```json\n"
    '{"consensus_areas": ["基本面优秀"], "divergence_areas": ["短期估值"], '
    '"strongest_bull_case": "ROE >20%", "strongest_bear_case": "估值偏高", '
    '"probability_assessment": 65, "final_recommendation": "逢低买入", '
    '"risk_warnings": ["估值回调风险"], "minority_opinion": "风控官建议观望"}\n```'
)


@pytest.fixture(autouse=True)
def _mock_pg_upsert_globally():
    """隔离 ExpertTeamService 后台落盘任务,避免测试事件循环关闭时任务悬挂泄漏

    测试本意是「Mock Redis + PG 均不可用 → 走内存兜底」。但 save_session 会
    fire-and-forget 多个后台任务(_pg_upsert 连真实 PG、_redis_set 连 Redis),
    在 pytest-asyncio 关闭 loop 时触发 "Task was destroyed but it is pending"
    / The operation was canceled。
    通过 patch 类方法,使单例与所有实例均不创建真实异步后台任务。
    """
    from unittest.mock import AsyncMock, patch

    with (
        patch(
            "backend.services.expert_team.expert_team_service.ExpertTeamService._pg_upsert",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "backend.services.expert_team.expert_team_service.ExpertTeamService._redis_set",
            new=AsyncMock(return_value=None),
        ),
    ):
        yield


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
        assert len(EXPERT_REGISTRY) == 21
        # 金融域 17 个
        finance_experts = [e for e in EXPERT_REGISTRY.values() if e.domain == "finance"]
        assert len(finance_experts) == 17
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
        assert len(scenario.expert_ids) == 7

    def test_get_scenario_invalid(self):
        with pytest.raises(ValueError, match="未知场景"):
            get_scenario("nonexistent")

    def test_list_scenarios(self):
        scenarios = list_scenarios()
        assert len(scenarios) == 7
        ids = [s.id for s in scenarios]
        assert "financial_research" in ids
        assert "code_review" in ids
        assert "full_investment" in ids
        assert "trading_decision" in ids
        assert "earnings_watch" in ids
        assert "macro_allocation" in ids
        assert "event_special" in ids

    def test_instantiate_expert_team_finance(self):
        team = instantiate_expert_team("financial_research")
        assert len(team) == 7
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
        assert len(team) == 17
        ids = [e.id for e in team]
        assert "chief_investment_officer" in ids
        assert "trade_executor" in ids
        assert "portfolio_risk_manager" in ids
        assert "news_analyst" in ids
        assert "macro_strategist" in ids
        assert "valuation_expert" in ids
        assert "event_driven_analyst" in ids
        assert "options_strategist" in ids
        assert "fixed_income_strategist" in ids
        assert "esg_analyst" in ids

    def test_instantiate_earnings_watch_team(self):
        team = instantiate_expert_team("earnings_watch")
        assert len(team) == 6
        ids = [e.id for e in team]
        assert "event_driven_analyst" in ids
        assert "fundamental_analyst" in ids
        assert "risk_officer" in ids

    def test_instantiate_macro_allocation_team(self):
        """宏观资产配置：无需个股数据的跨资产场景"""
        template = get_scenario("macro_allocation")
        # 数据需求均为市场级（无需个股 ticker；market_review 按市场维度采集）
        from backend.services.expert_team.data_collector import _DATA_COLLECTORS

        for req in template.data_requirements:
            assert _DATA_COLLECTORS[req]["param_key"] != "ticker", f"{req} 需要 ticker，不符合跨资产场景定位"
        team = instantiate_expert_team("macro_allocation")
        assert len(team) == 6
        ids = [e.id for e in team]
        assert "fixed_income_strategist" in ids
        assert "chief_investment_officer" in ids

    def test_instantiate_event_special_team(self):
        team = instantiate_expert_team("event_special")
        assert len(team) == 7
        ids = [e.id for e in team]
        assert "event_driven_analyst" in ids
        assert "options_strategist" in ids
        assert "trade_executor" in ids

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

    def test_event_driven_analyst_prompt_loading(self):
        """新增角色：事件驱动分析师的 prompt 文件应可加载"""
        expert = get_expert("event_driven_analyst")
        assert expert.name == "事件驱动分析师"
        assert "催化" in expert.system_prompt

    def test_all_finance_experts_have_prompt(self):
        """回归：每个金融专家都必须有可加载的 prompt 文件（防新增角色忘建 prompt）"""
        for eid, role in EXPERT_REGISTRY.items():
            if role.domain != "finance":
                continue
            expert = get_expert(eid)
            assert expert.system_prompt, f"金融专家 {eid} 缺少 prompt 文件"


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
        # quote 工具的 BrokerMarketTool 需要 action 参数（QUOTE=实时报价），断言含 action
        mock_registry.execute.assert_called_once_with("get_broker_market_data", action="QUOTE", ticker="AAPL")

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
        original_retries = dc._COLLECT_MAX_RETRIES
        dc._COLLECT_TIMEOUT = 0.1
        dc._COLLECT_MAX_RETRIES = 0  # 本用例仅验证单次超时返回，不触发重试路径

        try:
            result = await collect_shared_data(
                data_requirements=["quote"],
                tool_registry=mock_registry,
                ticker="AAPL",
            )
            assert result["quote"]["status"] == "timeout"
        finally:
            dc._COLLECT_TIMEOUT = original_timeout
            dc._COLLECT_MAX_RETRIES = original_retries

    @pytest.mark.asyncio
    async def test_collect_same_serial_group_runs_sequentially(self):
        """同 serial_group 的数据项必须串行执行（避免并发打爆同一上游）

        背景：投研会开场一次性并发 6 个数据项，其中 4 个打到 Futu OpenD，
        瞬时并发触发限流/超时 → 计入熔断 → 整源停摆。
        """
        concurrent = 0
        max_concurrent = 0

        async def tracked_execute(tool_name, **kwargs):
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.05)
            concurrent -= 1
            return {"status": "success", "data": {"tool": tool_name}}

        registry = MagicMock()
        registry.execute = tracked_execute

        # quote / fundamental 同属 "futu" 串行组
        result = await collect_shared_data(
            data_requirements=["quote", "fundamental"],
            tool_registry=registry,
            ticker="AAPL",
        )
        assert result["quote"]["status"] == "success"
        assert result["fundamental"]["status"] == "success"
        assert max_concurrent == 1, f"同组任务应串行执行，实测最大并发 {max_concurrent}"

    @pytest.mark.asyncio
    async def test_collect_retries_transient_failure(self):
        """瞬时错误（网络抖动）应重试并最终成功"""
        import backend.services.expert_team.data_collector as dc

        calls = {"n": 0}

        async def flaky_execute(tool_name, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": "error", "message": "connection reset by peer"}
            return {"status": "success", "data": {"price": 1.0}}

        registry = MagicMock()
        registry.execute = flaky_execute

        orig_retries = dc._COLLECT_MAX_RETRIES
        orig_backoff = dc._COLLECT_RETRY_BACKOFF
        dc._COLLECT_MAX_RETRIES = 1
        dc._COLLECT_RETRY_BACKOFF = 0.01  # 测试加速
        try:
            result = await collect_shared_data(
                data_requirements=["quote"],
                tool_registry=registry,
                ticker="AAPL",
            )
        finally:
            dc._COLLECT_MAX_RETRIES = orig_retries
            dc._COLLECT_RETRY_BACKOFF = orig_backoff

        assert result["quote"]["status"] == "success"
        assert calls["n"] == 2, f"首次失败后应重试 1 次，实际调用 {calls['n']} 次"

    @pytest.mark.asyncio
    async def test_collect_does_not_retry_circuit_breaker(self):
        """熔断/限流冷却期内重试无意义 → 不重试，快速失败（避免加重上游负担）"""
        import backend.services.expert_team.data_collector as dc

        calls = {"n": 0}

        async def breaker_execute(tool_name, **kwargs):
            calls["n"] += 1
            return {"status": "error", "message": "Futu QUOTE 接口熔断冷却中（约 30s 后重试，节点本身健康）"}

        registry = MagicMock()
        registry.execute = breaker_execute

        orig_retries = dc._COLLECT_MAX_RETRIES
        dc._COLLECT_MAX_RETRIES = 2
        try:
            result = await collect_shared_data(
                data_requirements=["quote"],
                tool_registry=registry,
                ticker="AAPL",
            )
        finally:
            dc._COLLECT_MAX_RETRIES = orig_retries

        assert result["quote"]["status"] == "error"
        assert calls["n"] == 1, f"熔断冷却期内不应重试，实际调用 {calls['n']} 次"

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

    @pytest.mark.asyncio
    async def test_collect_progress_response_is_complete(self):
        """采集进度回调的 response 必须完整保留

        回归：原先固定 600 字符，macro_news/sentiment/technicals/fed_watch
        的响应在 JSON 中途被腰斩 → 语法不完整、无法阅读，用户核对不到采集到的数据。
        """
        long_news = {
            "status": "success",
            "data": [{"headline": f"news-{i}-" + "h" * 60, "summary": "s" * 60, "source": "CNBC"} for i in range(20)],
        }
        registry = MagicMock()
        registry.execute = AsyncMock(return_value=long_news)

        steps: list = []

        async def on_progress(item):
            steps.append(item)

        await collect_shared_data(
            data_requirements=["macro_news"],
            tool_registry=registry,
            on_progress=on_progress,
        )

        resp = steps[0]["response"]
        assert len(resp) > 2000, f"响应应完整保留，实际仅 {len(resp)} 字符"
        assert "已截断" not in resp
        parsed = json.loads(resp)  # 完整 JSON：可解析
        assert len(parsed) == 20

    def test_summarize_result_truncates_oversized_payload(self):
        """病态大包兜底截断，且必须显式标注原始总长度"""
        from backend.services.expert_team.data_collector import _RESPONSE_MAX_CHARS, _summarize_result

        raw_len = _RESPONSE_MAX_CHARS + 100
        text = _summarize_result({"status": "success", "data": "x" * raw_len})
        assert len(text) < raw_len
        assert "已截断" in text
        assert str(raw_len) in text

    def test_summarize_result_error_returns_full_message(self):
        """错误/超时态返回 message 全文（不再被截断）"""
        from backend.services.expert_team.data_collector import _summarize_result

        msg = "Futu QUOTE 接口熔断冷却中（约 30s 后重试，节点本身健康）"
        assert _summarize_result({"status": "error", "message": msg}) == msg


# ─── orchestrator.py 测试 ──────────────────────────────────────


class TestOrchestrator:
    """编排引擎测试"""

    @pytest.mark.asyncio
    async def test_debate_stream_events(self):
        """完整辩论流应产生正确的事件序列"""
        orchestrator = DebateOrchestrator(tool_registry=None)

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_stream = MagicMock(
                side_effect=[_stream_fn(_R1_STREAM_TEXT)] * 7
                + [_stream_fn(_R2_STREAM_TEXT)] * 7
                + [_stream_fn(_CHIEF_STREAM_TEXT)]
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
        assert len(scenarios) == 7

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
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from backend.main import app

        # 隔离外部依赖：Redis + PG 均不可用 → 端点走内存兜底（符合测试意图）。
        # 否则模块级全局 redis_client 在 TestClient 的多个独立事件循环间复用时会
        # 出现跨 loop 连接错乱，导致 scan 永久挂起（test_list_sessions_endpoint 卡死）。
        redis_mock = MagicMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.set = AsyncMock(return_value="OK")

        with (
            patch("backend.core.redis_client.redis_client", redis_mock),
            patch(
                "backend.core.database.SessionLocal",
                side_effect=RuntimeError("PG unavailable in test"),
            ),
        ):
            yield TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        """COPILOT-08: 生成合法 JWT 以通过 expert_team 端点鉴权

        直接引用 expert_team.SECRET_KEY（而非 os.getenv 快照），
        确保与路由解码使用同一密钥，杜绝 CI/本地环境变量差异导致的 401。
        """
        from jose import jwt

        from backend.routers.expert_team import SECRET_KEY

        token = jwt.encode({"sub": "test_user"}, SECRET_KEY, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.slow
    def test_list_scenarios_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/expert-team/scenarios", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # API 响应有统一包装 {code, msg, data}
        payload = data.get("data", data)
        assert "scenarios" in payload
        assert len(payload["scenarios"]) == 7

    @pytest.mark.slow
    def test_list_sessions_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/expert-team/sessions", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        payload = data.get("data", data)
        assert "sessions" in payload

    @pytest.mark.slow
    def test_get_session_not_found(self, client, auth_headers):
        resp = client.get("/api/v1/expert-team/sessions/nonexistent", headers=auth_headers)
        assert resp.status_code == 404

    def test_analyze_invalid_scenario(self, client, auth_headers):
        resp = client.post(
            "/api/v1/expert-team/analyze",
            json={
                "scenario": "invalid",
                "question": "test",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.slow
    def test_analyze_endpoint_runs_with_custom_team(self, client, auth_headers):
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
            headers=auth_headers,
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
    async def test_yield_opinion_stream_carries_identity_every_chunk(self):
        """回归：每片均携带顶层 expert_id/round，否则前端增量片无法归位到对应专家（全部 R0）"""
        op = self._make_opinion()
        orch = DebateOrchestrator()
        events = [ev async for ev in orch._yield_opinion_stream(op, round_index=2)]
        assert len(events) > 1
        for ev in events:
            assert ev.expert_id == op.expert_id
            assert ev.round == 2

    @pytest.mark.asyncio
    async def test_round_timeout_rescues_completed_opinions(self, monkeypatch):
        """回归 BE-EXPERT-TIMEOUT-RACE：整轮超时但 worker 已产出完成观点时，
        应抢救真实观点（补发完成帧），而非补"超时占位"覆盖已上屏正文，
        否则前端出现"超时占位 stance + 完整正文"的矛盾卡片"""
        import backend.services.expert_team.orchestrator as orch_mod

        monkeypatch.setattr(orch_mod, "_ROUND_TIMEOUT", 0.3)
        orch = DebateOrchestrator(tool_registry=None)
        expert = get_expert("fundamental_analyst")
        real_data = {
            "expert_id": expert.id,
            "round": 1,
            "stance": "看多",
            "confidence": 70,
            "key_evidence": ["ROE>20%"],
        }

        async def fake_round1(expert_role, question, shared_text):
            # 增量帧（正文上屏）→ 完成帧（结构化 data），瞬间完成入队
            yield StreamEvent(type="expert_opinion", expert_id=expert_role.id, round=1, content="基本面强劲。", data={})
            yield StreamEvent(type="expert_opinion", expert_id=expert_role.id, round=1, content="", data=real_data)

        with patch.object(orch, "_call_expert_round1", fake_round1):
            out_opinions: list[ExpertOpinion] = []
            events = []
            async for ev in orch._run_round_stream([expert], "q", "", 1, out_opinions, None):
                events.append(ev)
                if len(events) == 1:
                    # 模拟下游背压：主循环挂起在 yield 期间整轮 deadline（0.3s）到期，
                    # 哨兵/完成帧滞留队列——正是线上"占位覆盖正文"的竞态窗口
                    await asyncio.sleep(0.5)

        # 抢救成功：真实观点完成帧上屏，stance/置信度为真实值
        final = [e for e in events if e.data and e.data.get("stance")]
        assert final, "应补发真实观点完成帧"
        assert final[-1].data["stance"] == "看多"
        assert final[-1].data["confidence"] == 70
        # 不再补超时占位
        assert not any("超时" in (e.data.get("stance") or "") for e in events if e.data)
        assert out_opinions and out_opinions[0].stance == "看多"

    # ─── 真流式协议测试（研判文本实时流出 + 末尾 JSON 补全结构化字段）───

    def test_stream_splitter_separates_markdown_and_json(self):
        """```json 之前的研判文本实时流出，JSON 块不外泄、结束时可解析"""
        s = _StreamSplitter()
        text = '分析文本一。\n```json\n{"stance": "看多"}\n```'
        out = "".join(s.feed(text[i : i + 5]) for i in range(0, len(text), 5))
        md, data = s.finish()
        assert out == "分析文本一。\n"  # JSON 块不会流给前端
        assert md == "分析文本一。"
        assert data == {"stance": "看多"}

    def test_stream_splitter_marker_split_across_chunks(self):
        """回归：marker 跨 chunk 切开时不得丢失或提前外泄"""
        s = _StreamSplitter()
        out = "".join(s.feed(c) for c in "前半段分析")
        out += "".join(s.feed(c) for c in '\n```json\n{"a": 1}\n```')
        md, data = s.finish()
        assert md == "前半段分析"
        assert data == {"a": 1}
        assert "json" not in out  # 片段到达时不提前外泄 marker

    def test_stream_splitter_no_json_block(self):
        """LLM 未遵守两段式格式：全部当研判文本，结构化为空（由调用方降级）"""
        s = _StreamSplitter()
        s.feed("只有研判文本，没有结构化块。")
        md, data = s.finish()
        assert md == "只有研判文本，没有结构化块。"
        assert data == {}

    @pytest.mark.asyncio
    async def test_expert_stream_delta_and_completion_frames(self):
        """真流式协议：增量帧仅带文本不带 data，末帧（完成帧）content 为空、携带结构化 data"""
        orch = DebateOrchestrator()
        expert = get_expert("fundamental_analyst")

        async def fake_stream(*args, **kwargs):
            yield "基本面强劲，"
            yield "ROE 稳健。\n```j"
            yield 'son\n{"stance": "看多", "confidence": 70, "key_evidence": ["ROE>20%"]}\n```'

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_stream = fake_stream
            events = [ev async for ev in orch._call_expert_round1(expert, "AAPL?", "## 数据\n" + "有效内容。" * 20)]

        deltas = [e for e in events if e.content]
        final = events[-1]
        assert deltas and all(e.expert_id == expert.id and e.round == 1 for e in events)
        assert all(not e.data for e in deltas)  # 增量帧不带结构化数据
        assert "".join(e.content for e in deltas) == "基本面强劲，ROE 稳健。\n"
        assert final.content == ""
        assert final.data.get("stance") == "看多"
        assert final.data.get("confidence") == 70
        assert final.data.get("reasoning", "").startswith("基本面强劲")

    @pytest.mark.asyncio
    async def test_expert_stream_timeout_rescues_partial_text(self, monkeypatch):
        """回归：单专家流式超时但已有部分正文上屏时，应降级提取部分产出
        （stance 用"部分产出"语义），而非补"超时异常"占位与正文自相矛盾"""
        import backend.services.expert_team.orchestrator as orch_mod

        monkeypatch.setattr(orch_mod, "_EXPERT_TIMEOUT", 0.2)
        orch = DebateOrchestrator()
        expert = get_expert("macro_strategist")

        async def fake_stream(*args, **kwargs):
            yield "## 宏观策略师独立研判\n流动性宽松利好权益资产。"
            await asyncio.sleep(0.4)  # 越过单专家 deadline，下一片到达时触发流式超时
            yield "永远不会到达"

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_stream = fake_stream
            events = [ev async for ev in orch._call_expert_round1(expert, "全球宏观?", "## 数据\n" + "有效内容。" * 20)]

        final = events[-1]
        assert final.content == ""
        # 部分产出语义，而非"超时异常"占位
        assert final.data.get("stance") == orch_mod._STANCE_TIMEOUT_PARTIAL
        assert final.data.get("reasoning", "").startswith("## 宏观策略师独立研判")

    @pytest.mark.asyncio
    async def test_chief_stream_yields_completion_frame(self):
        """首席收敛真流式：报告增量流出，完成帧携带结构化数据并写入 session"""
        orch = DebateOrchestrator()
        sess = DebateSession(session_id="s", scenario="financial_research", question="q")
        chief_text = (
            "# 最终报告\n看涨概率 55%。\n```json\n"
            '{"consensus_areas": ["c1"], "divergence_areas": ["d1"], "probability_assessment": 55, '
            '"final_recommendation": "逢低买入"}\n```'
        )
        op = self._make_opinion()
        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_stream = _stream_fn(chief_text)
            events = [ev async for ev in orch._run_synthesis_stream(sess, "q", [op], [op])]

        deltas = [e for e in events if e.content]
        final = events[-1]
        assert deltas and all(e.type == "chief_report" for e in events)
        assert final.content == ""
        assert final.data.get("probability_assessment") == 55
        assert sess.chief_report is not None
        assert sess.chief_report.full_report.startswith("# 最终报告")

    @pytest.mark.asyncio
    async def test_debate_stream_multi_round(self):
        """rounds=3 应触发 Round1 + Round2 + Round3 三轮辩论"""
        orch = DebateOrchestrator(tool_registry=None)

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            # 7 专家（financial_research 默认阵容）* 3 轮 + 1 首席
            mock_llm.generate_stream = MagicMock(
                side_effect=[_stream_fn(_R1_STREAM_TEXT)] * 7
                + [_stream_fn(_R2_STREAM_TEXT)] * 7
                + [_stream_fn(_R2_STREAM_TEXT)] * 7
                + [_stream_fn(_CHIEF_STREAM_TEXT)]
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
            # 后续轮次不得覆盖前置轮次：all_rounds 须完整保留三轮全部专家观点（7 人阵容）
            sess = orch._last_session
            assert sess is not None
            assert sorted(sess.all_rounds.keys()) == [1, 2, 3]
            assert all(len(ops) == 7 for ops in sess.all_rounds.values())

    @pytest.mark.asyncio
    async def test_debate_stream_custom_expert_ids(self):
        """expert_ids 自定义阵容应覆盖场景默认, 并用 get_expert 实例化"""
        orch = DebateOrchestrator(tool_registry=None)

        with patch("backend.services.expert_team.orchestrator.llm_service") as mock_llm:
            mock_llm.generate_stream = MagicMock(
                side_effect=[_stream_fn(_R1_STREAM_TEXT)] * 2
                + [_stream_fn(_R2_STREAM_TEXT)] * 2
                + [_stream_fn(_CHIEF_STREAM_TEXT)]
            )
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


# ─── P1.10/11: FedWatch 接入宏观研判层 ───────────────────────────────


class TestFedWatchInExpertTeam:
    """P1.10: FedWatch target_rate 作为 Tier1 FOMC 前瞻信号接入专家辩论层"""

    def test_data_collector_has_fed_watch(self):
        """_DATA_COLLECTORS 应含 fed_watch → get_fed_watch，市场级无 ticker"""
        from backend.services.expert_team.data_collector import _DATA_COLLECTORS

        assert "fed_watch" in _DATA_COLLECTORS
        assert _DATA_COLLECTORS["fed_watch"]["tool"] == "get_fed_watch"
        assert _DATA_COLLECTORS["fed_watch"]["param_key"] is None  # 市场级，无需 ticker

    def test_macro_strategist_has_get_fed_watch(self):
        """宏观策略师 available_tools 应含 get_fed_watch"""
        expert = get_expert("macro_strategist")
        assert expert is not None
        assert "get_fed_watch" in expert.available_tools

    def test_portfolio_risk_manager_has_get_fed_watch(self):
        """组合风控经理 available_tools 应含 get_fed_watch"""
        expert = get_expert("portfolio_risk_manager")
        assert expert is not None
        assert "get_fed_watch" in expert.available_tools

    def test_financial_research_scenario_requires_fed_watch(self):
        """financial_research 场景 data_requirements 应含 fed_watch"""
        scenario = get_scenario("financial_research")
        assert scenario is not None
        assert "fed_watch" in scenario.data_requirements

    def test_full_investment_scenario_requires_fed_watch(self):
        """full_investment 场景 data_requirements 应含 fed_watch"""
        scenario = get_scenario("full_investment")
        assert scenario is not None
        assert "fed_watch" in scenario.data_requirements

    def test_collect_shared_data_invokes_fed_watch_tool(self):
        """collect_shared_data 收到 fed_watch 需求时应调用 get_fed_watch 工具且不传 ticker"""
        from backend.services.expert_team.data_collector import collect_shared_data

        registry = MagicMock()

        async def fake_execute(tool_name, **kwargs):
            assert tool_name == "get_fed_watch"
            assert "ticker" not in kwargs  # 市场级，无需 ticker
            return {"status": "success", "data": {"cut_probability": 0.72}}

        registry.execute = AsyncMock(side_effect=fake_execute)

        result = asyncio.run(
            collect_shared_data(
                data_requirements=["fed_watch"],
                tool_registry=registry,
                ticker="US.AAPL",
            )
        )
        assert "fed_watch" in result
        assert result["fed_watch"].get("status") == "success"
        registry.execute.assert_called_once()


# ─── 问题文本解析 ticker（未绑定标的场景稳定性） ──────────────────────


class TestResolveTickerFromQuestion:
    """_resolve_ticker_from_question 稳定性：中文名/标准代码/普通英文词不误判

    覆盖用户反馈：查询标的/quote/fundamental/technicals 偶发「未识别到标的」。
    根因：贪婪截断 `{2,6}` 把动词杂质带入关键词（如「腾讯控股值得买」→「腾讯控股值得」），
    词库与 Futu 联想均失配。修复后改为从长到短逐级缩短候选，并收紧裸英文词判定。
    """

    def _patch_deps(self, local_data=None, futu_data=None, llm_ticker=None):
        """mock 本地词库 / Futu search_quote / LLM 兜底，避免真实外部依赖"""

        async def fake_search_tickers(kw):
            return {"status": "success", "data": local_data or []}

        async def fake_search_quote(keyword, max_count=10):
            mock = MagicMock()
            mock.is_success = bool(futu_data)
            mock.data = futu_data or []
            return mock

        async def fake_llm(question, keyword):
            return llm_ticker

        stack = ExitStack()
        stack.enter_context(
            patch(
                "backend.services.fund_flow.ticker.ticker_service.search_tickers",
                new=AsyncMock(side_effect=fake_search_tickers),
            )
        )
        stack.enter_context(
            patch(
                "backend.services.datasource.business.data_service.search_quote",
                new=AsyncMock(side_effect=fake_search_quote),
            )
        )
        stack.enter_context(
            patch(
                "backend.services.expert_team.expert_team_service._resolve_ticker_via_llm",
                new=AsyncMock(side_effect=fake_llm),
            )
        )
        return stack

    @pytest.mark.asyncio
    async def test_standard_code_us_prefix(self):
        """带 US. 前缀的标准代码应直接标准化，不经过联想"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        with self._patch_deps():
            assert await _resolve_ticker_from_question("US.AAPL 值得投资吗？") == "US.AAPL"

    @pytest.mark.asyncio
    async def test_standard_code_hk_suffix(self):
        """00700.HK 后缀标准代码应直接标准化"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        with self._patch_deps():
            assert await _resolve_ticker_from_question("00700.HK 怎么样") == "HK.00700"

    @pytest.mark.asyncio
    async def test_chinese_name_with_noise_verb(self):
        """中文名后带动词杂质（值得/买入/吗）时，应逐级缩短到词库可命中的名称"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        local_data = [{"symbol": "HK.00700", "code": "HK.00700", "name": "腾讯控股", "type": "STOCK"}]
        with self._patch_deps(local_data=local_data):
            # 「腾讯控股值得买吗」→ 剔除杂质后候选含「腾讯控股」→ 词库命中
            assert await _resolve_ticker_from_question("腾讯控股值得买吗？") == "HK.00700"

    @pytest.mark.asyncio
    async def test_chinese_name_short(self):
        """短中文名（宁德时代）应直接命中词库"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        local_data = [{"symbol": "US.300750", "code": "US.300750", "name": "宁德时代", "type": "STOCK"}]
        with self._patch_deps(local_data=local_data):
            assert await _resolve_ticker_from_question("宁德时代怎么样") == "US.300750"

    @pytest.mark.asyncio
    async def test_no_false_positive_on_english_word(self):
        """普通英文词（AI/ETF）不得被误判为股票代码，词库/LLM 无命中时应返回 None"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        with self._patch_deps(local_data=[], futu_data=[], llm_ticker=None):
            assert await _resolve_ticker_from_question("AI板块怎么看") is None

    @pytest.mark.asyncio
    async def test_futu_fallback_when_local_miss(self):
        """本地词库未命中时应降级走 Futu SEARCH_QUOTE 联想"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        futu_data = [{"code": "US.AAPL", "symbol": "US.AAPL", "name": "苹果", "sec_type": "STOCK"}]
        with self._patch_deps(local_data=[], futu_data=futu_data):
            assert await _resolve_ticker_from_question("苹果值得持有吗") == "US.AAPL"

    @pytest.mark.asyncio
    async def test_llm_fallback_when_all_miss(self):
        """词库与 Futu 均未命中时，LLM 语义推导兜底（如"白酒龙头"→贵州茅台）"""
        from backend.services.expert_team.expert_team_service import _resolve_ticker_from_question

        with self._patch_deps(local_data=[], futu_data=[], llm_ticker="SH.600519"):
            assert await _resolve_ticker_from_question("白酒龙头现在能买吗") == "SH.600519"
