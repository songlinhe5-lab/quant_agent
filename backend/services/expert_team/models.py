"""
专家团数据模型
定义专家角色、观点、辩论会话、场景模板等核心数据结构
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ExpertRole(BaseModel):
    """专家角色定义"""

    id: str  # "fundamental_analyst"
    name: str  # "基本面分析师"
    domain: Literal["finance", "code", "strategy"]
    team: str = ""  # 所属团队: "analyst" / "researcher" / "trader" / "risk" / "management" / "code"
    system_prompt: str = ""  # 角色 prompt (从 prompts/ 目录加载)
    bias: Optional[str] = None  # "bullish" / "bearish" / "neutral" (金融域)
    available_tools: list[str] = Field(default_factory=list)  # 该专家可调用的工具子集
    description: str = ""  # 角色简介 (展示用)


class ExpertOpinion(BaseModel):
    """单个专家在某一轮的研判输出"""

    expert_id: str
    round: int  # 1 or 2
    stance: str  # 核心观点 (<=200字)
    confidence: int = Field(ge=0, le=100)  # 置信度 0-100
    key_evidence: list[str] = Field(default_factory=list)  # 关键依据
    reasoning: str = ""  # 完整推理过程
    # Round 2 专属字段
    challenges: list[str] = Field(default_factory=list)  # 对其他专家的质疑
    confidence_delta: int = 0  # 置信度变化 (+/-)
    revised_stance: str = ""  # 修正后观点


class ChiefReport(BaseModel):
    """首席分析师最终收敛报告"""

    consensus_areas: list[str] = Field(default_factory=list)  # 共识区
    divergence_areas: list[str] = Field(default_factory=list)  # 分歧区
    strongest_bull_case: str = ""  # 最强看多论据
    strongest_bear_case: str = ""  # 最强看空论据
    probability_assessment: int = Field(ge=0, le=100, default=50)  # 看涨概率
    final_recommendation: str = ""  # 最终建议
    risk_warnings: list[str] = Field(default_factory=list)  # 风险提示
    minority_opinion: str = ""  # 少数派意见保留
    full_report: str = ""  # 完整报告 Markdown


class DebateSession(BaseModel):
    """辩论会话完整状态"""

    session_id: str
    scenario: str  # "financial_research" / "code_review"
    question: str
    context: dict[str, Any] = Field(default_factory=dict)  # 额外上下文 (ticker, code 等)
    shared_data: dict[str, Any] = Field(default_factory=dict)  # 共享数据包
    experts: list[ExpertRole] = Field(default_factory=list)
    round1_opinions: list[ExpertOpinion] = Field(default_factory=list)
    round2_opinions: list[ExpertOpinion] = Field(default_factory=list)
    chief_report: Optional[ChiefReport] = None
    status: Literal["pending", "collecting", "round1", "round2", "synthesis", "done", "error"] = "pending"
    error_message: str = ""
    created_at: str = ""
    completed_at: str = ""


class ScenarioTemplate(BaseModel):
    """场景模板：预配置的专家组合"""

    id: str  # "financial_research"
    name: str  # "金融投研"
    domain: Literal["finance", "code", "strategy"]
    description: str = ""
    expert_ids: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)  # 需要预采集的数据类型
    chief_prompt_file: str = "chief_analyst.md"


# ─── API 请求/响应模型 ─────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """发起专家团分析请求"""

    scenario: str  # 场景模板 ID
    question: str  # 用户问题
    ticker: Optional[str] = None  # 金融域: 标的代码
    code_context: Optional[str] = None  # 代码域: 代码片段
    extra_context: dict[str, Any] = Field(default_factory=dict)


class SessionSummary(BaseModel):
    """会话摘要 (列表展示用)"""

    session_id: str
    scenario: str
    question: str
    status: str
    expert_count: int
    probability_assessment: Optional[int] = None
    created_at: str
    completed_at: str = ""


# ─── SSE 事件模型 ──────────────────────────────────────────────


class StreamEvent(BaseModel):
    """SSE 流式事件"""

    type: Literal[
        "status",  # 状态变更
        "expert_opinion",  # 专家观点输出
        "round_complete",  # 某轮完成
        "chief_report",  # 首席报告
        "error",  # 错误
        "done",  # 全部完成
    ]
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
