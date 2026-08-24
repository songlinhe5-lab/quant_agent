"""
专家角色注册表 + 场景模板
定义所有可用的专家角色和预配置的场景组合

专家团组织架构 (21位):
├── 📊 分析师团队 (analyst) - 11位
│   ├── fundamental_analyst   基本面分析师
│   ├── technical_analyst     技术面分析师
│   ├── macro_strategist      宏观策略师
│   ├── valuation_expert      估值专家
│   ├── industry_analyst      行业分析师
│   ├── sentiment_analyst     情绪分析师
│   ├── news_analyst          新闻分析师
│   ├── event_driven_analyst  事件驱动分析师
│   ├── options_strategist    期权策略师
│   ├── fixed_income_strategist 固收策略师
│   └── esg_analyst           ESG/治理分析师
├── 🔬 研究员团队 (researcher) - 2位
│   ├── industry_researcher   产业研究员
│   └── quant_researcher      量化研究员
├── 💱 交易员 (trader) - 1位
│   └── trade_executor        交易执行专家
├── 🛡️ 风险管理 (risk) - 2位
│   ├── risk_officer          风控官
│   └── portfolio_risk_manager 组合风控经理
├── 👔 管理层 (management) - 1位
│   └── chief_investment_officer 首席投资官
└── 💻 代码域 (code) - 4位
    ├── code_architect        架构师
    ├── security_expert       安全专家
    ├── performance_expert    性能专家
    └── maintainability_expert 可维护性专家
"""

from pathlib import Path

from backend.services.expert_team.models import ExpertRole, ScenarioTemplate

# ─── Prompt 文件目录 ───────────────────────────────────────────
_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(domain: str, filename: str) -> str:
    """从 prompts/ 目录加载专家 prompt 模板"""
    path = _PROMPTS_DIR / domain / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 分析师团队 (analyst) - 信息解读与价值发现
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FUNDAMENTAL_ANALYST = ExpertRole(
    id="fundamental_analyst",
    name="基本面分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_fundamental_data", "analyze_financial_report"],
    description="专注三表质量、ROE 趋势、现金流健康度、盈利可持续性",
)

TECHNICAL_ANALYST = ExpertRole(
    id="technical_analyst",
    name="技术面分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["calculate_technical_indicators", "get_broker_market_data"],
    description="专注价格趋势、支撑压力位、量价关系、技术形态识别",
)

MACRO_STRATEGIST = ExpertRole(
    id="macro_strategist",
    name="宏观策略师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_macro_news", "get_macro_calendar", "get_fred_macro_data", "get_fed_watch"],
    description="专注政策影响、利率周期、行业景气度、全球资金流向",
)

VALUATION_EXPERT = ExpertRole(
    id="valuation_expert",
    name="估值专家",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_fundamental_data", "web_search"],
    description="专注 DCF 估值、PE/PB 历史分位、同业对比、安全边际",
)

INDUSTRY_ANALYST = ExpertRole(
    id="industry_analyst",
    name="行业分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_company_news", "web_search"],
    description="专注行业格局、竞争态势、市场空间、产业链地位、行业生命周期",
)

SENTIMENT_ANALYST = ExpertRole(
    id="sentiment_analyst",
    name="情绪分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_macro_sentiment_history", "get_broker_market_data"],
    description="专注市场情绪指标、资金流向、持仓结构、散户/机构行为分析",
)

NEWS_ANALYST = ExpertRole(
    id="news_analyst",
    name="新闻分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_macro_news", "get_company_news", "web_search"],
    description="专注新闻质量评估、信息可信度、叙事转变识别、市场定价充分性、信号与噪音分离",
)

EVENT_DRIVEN_ANALYST = ExpertRole(
    id="event_driven_analyst",
    name="事件驱动分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_company_news", "web_search", "compare_earnings_expectations"],
    description="专注并购重组、财报预期差、政策催化、解禁/回购等催化剂事件的时间表与定价充分性",
)

OPTIONS_STRATEGIST = ExpertRole(
    id="options_strategist",
    name="期权策略师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_option_volatility", "get_option_strategy_lab", "get_broker_market_data"],
    description="专注隐含波动率、PCR、期限结构、期权组合策略(备兑/价差/对冲)与尾部保护",
)

FIXED_INCOME_STRATEGIST = ExpertRole(
    id="fixed_income_strategist",
    name="固收策略师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["get_fred_macro_data", "get_fed_watch", "get_macro_news"],
    description="专注利率曲线、信用利差、股债性价比、跨资产轮动信号",
)

ESG_ANALYST = ExpertRole(
    id="esg_analyst",
    name="ESG/治理分析师",
    domain="finance",
    team="analyst",
    bias="neutral",
    available_tools=["web_search", "get_company_news"],
    description="专注 ESG 评级、公司治理质量、监管合规风险与可持续发展溢价",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔬 研究员团队 (researcher) - 深度研究与量化验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INDUSTRY_RESEARCHER = ExpertRole(
    id="industry_researcher",
    name="产业研究员",
    domain="finance",
    team="researcher",
    bias="neutral",
    available_tools=["web_search", "get_fundamental_data"],
    description="专注产业链上下游映射、竞争壁垒(护城河)、技术路线演变、行业拐点判断",
)

QUANT_RESEARCHER = ExpertRole(
    id="quant_researcher",
    name="量化研究员",
    domain="finance",
    team="researcher",
    bias="neutral",
    available_tools=["calculate_technical_indicators", "get_fundamental_data"],
    description="专注因子有效性、统计套利、回测验证、信号衰减、量化风险模型",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💱 交易员 (trader) - 执行与仓位管理
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRADE_EXECUTOR = ExpertRole(
    id="trade_executor",
    name="交易执行专家",
    domain="finance",
    team="trader",
    bias="neutral",
    available_tools=["get_broker_market_data", "calculate_technical_indicators"],
    description="专注择时策略、仓位管理、执行算法(TWAP/VWAP)、滑点控制、止盈止损纪律",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🛡️ 风险管理 (risk) - 风险识别与防御
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RISK_OFFICER = ExpertRole(
    id="risk_officer",
    name="风控官",
    domain="finance",
    team="risk",
    bias="bearish",  # 天然偏空，负责发现风险
    available_tools=["get_macro_sentiment_history", "get_company_news"],
    description="专注尾部风险、黑天鹅预警、仓位管理、流动性危机",
)

PORTFOLIO_RISK_MANAGER = ExpertRole(
    id="portfolio_risk_manager",
    name="组合风控经理",
    domain="finance",
    team="risk",
    bias="bearish",
    available_tools=["get_macro_sentiment_history", "get_fred_macro_data", "get_fed_watch"],
    description="专注组合层面风险度量(VaR/CVaR)、相关性矩阵、压力测试、对冲策略、回撤控制",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 👔 管理层 (management) - 战略决策与资源配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CHIEF_INVESTMENT_OFFICER = ExpertRole(
    id="chief_investment_officer",
    name="首席投资官",
    domain="finance",
    team="management",
    bias="neutral",
    available_tools=["get_fundamental_data", "get_macro_news", "web_search"],
    description="专注大类资产配置、战略方向判断、投委会决策框架、长期复利思维、能力圈边界",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💻 代码域 (code) - 多视角代码审查
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CODE_ARCHITECT = ExpertRole(
    id="code_architect",
    name="架构师",
    domain="code",
    team="code",
    available_tools=[],
    description="专注分层合理性、依赖方向、扩展性、设计模式选择",
)

SECURITY_EXPERT = ExpertRole(
    id="security_expert",
    name="安全专家",
    domain="code",
    team="code",
    available_tools=[],
    description="专注注入攻击、XSS、权限漏洞、敏感数据泄露、依赖安全",
)

PERFORMANCE_EXPERT = ExpertRole(
    id="performance_expert",
    name="性能专家",
    domain="code",
    team="code",
    available_tools=[],
    description="专注热路径优化、内存泄漏、GC 压力、并发瓶颈、I/O 阻塞",
)

MAINTAINABILITY_EXPERT = ExpertRole(
    id="maintainability_expert",
    name="可维护性专家",
    domain="code",
    team="code",
    available_tools=[],
    description="专注命名规范、圈复杂度、测试覆盖、文档完整性、代码重复",
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 专家注册表 (按团队分组)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXPERT_REGISTRY: dict[str, ExpertRole] = {
    # 📊 分析师团队 (analyst)
    "fundamental_analyst": FUNDAMENTAL_ANALYST,
    "technical_analyst": TECHNICAL_ANALYST,
    "macro_strategist": MACRO_STRATEGIST,
    "valuation_expert": VALUATION_EXPERT,
    "industry_analyst": INDUSTRY_ANALYST,
    "sentiment_analyst": SENTIMENT_ANALYST,
    "news_analyst": NEWS_ANALYST,
    "event_driven_analyst": EVENT_DRIVEN_ANALYST,
    "options_strategist": OPTIONS_STRATEGIST,
    "fixed_income_strategist": FIXED_INCOME_STRATEGIST,
    "esg_analyst": ESG_ANALYST,
    # 🔬 研究员团队 (researcher)
    "industry_researcher": INDUSTRY_RESEARCHER,
    "quant_researcher": QUANT_RESEARCHER,
    # 💱 交易员 (trader)
    "trade_executor": TRADE_EXECUTOR,
    # 🛡️ 风险管理 (risk)
    "risk_officer": RISK_OFFICER,
    "portfolio_risk_manager": PORTFOLIO_RISK_MANAGER,
    # 👔 管理层 (management)
    "chief_investment_officer": CHIEF_INVESTMENT_OFFICER,
    # 💻 代码域 (code)
    "code_architect": CODE_ARCHITECT,
    "security_expert": SECURITY_EXPERT,
    "performance_expert": PERFORMANCE_EXPERT,
    "maintainability_expert": MAINTAINABILITY_EXPERT,
}

# 团队分组索引
TEAM_GROUPS: dict[str, list[str]] = {
    "analyst": [
        "fundamental_analyst",
        "technical_analyst",
        "macro_strategist",
        "valuation_expert",
        "industry_analyst",
        "sentiment_analyst",
        "news_analyst",
        "event_driven_analyst",
        "options_strategist",
        "fixed_income_strategist",
        "esg_analyst",
    ],
    "researcher": ["industry_researcher", "quant_researcher"],
    "trader": ["trade_executor"],
    "risk": ["risk_officer", "portfolio_risk_manager"],
    "management": ["chief_investment_officer"],
    "code": ["code_architect", "security_expert", "performance_expert", "maintainability_expert"],
}

TEAM_NAMES: dict[str, str] = {
    "analyst": "📊 分析师团队",
    "researcher": "🔬 研究员团队",
    "trader": "💱 交易员",
    "risk": "🛡️ 风险管理",
    "management": "👔 管理层",
    "code": "💻 代码域",
}


def get_expert(expert_id: str) -> ExpertRole:
    """获取专家角色 (带 prompt 加载)"""
    expert = EXPERT_REGISTRY.get(expert_id)
    if not expert:
        raise ValueError(f"未知专家 ID: {expert_id}")

    # 延迟加载 prompt 文件
    if not expert.system_prompt:
        domain_dir = "finance" if expert.domain == "finance" else "code"
        prompt_file = f"{expert_id.replace('_analyst', '').replace('_expert', '').replace('_officer', '').replace('_strategist', '')}.md"
        # 尝试多种文件名
        for candidate in [f"{expert_id}.md", prompt_file]:
            prompt = _load_prompt(domain_dir, candidate)
            if prompt:
                expert = expert.model_copy(update={"system_prompt": prompt})
                break

    return expert


def get_team_members(team: str) -> list[ExpertRole]:
    """获取指定团队的所有专家"""
    member_ids = TEAM_GROUPS.get(team, [])
    return [get_expert(eid) for eid in member_ids]


def list_teams() -> dict[str, list[ExpertRole]]:
    """列出所有团队及其成员"""
    return {team: get_team_members(team) for team in TEAM_GROUPS}


# ─── 场景模板 ──────────────────────────────────────────────────

SCENARIO_TEMPLATES: dict[str, ScenarioTemplate] = {
    "financial_research": ScenarioTemplate(
        id="financial_research",
        name="金融投研",
        domain="finance",
        description="标准多维研判个股/资产：基本面 + 技术面 + 宏观 + 估值 + 行业 + 新闻 + 风控（7人轻量团）",
        expert_ids=[
            "fundamental_analyst",
            "technical_analyst",
            "macro_strategist",
            "valuation_expert",
            "industry_analyst",
            "news_analyst",
            "risk_officer",
        ],
        data_requirements=["quote", "fundamental", "technicals", "macro_news", "sentiment", "fed_watch"],
        chief_prompt_file="chief_analyst.md",
    ),
    "full_investment": ScenarioTemplate(
        id="full_investment",
        name="完整投决会",
        domain="finance",
        description="模拟完整投资决策委员会：分析师 + 研究员 + 交易员 + 风控 + 管理层全链路研判（17人全员）",
        expert_ids=[
            "fundamental_analyst",
            "technical_analyst",
            "macro_strategist",
            "valuation_expert",
            "industry_analyst",
            "sentiment_analyst",
            "news_analyst",
            "event_driven_analyst",
            "options_strategist",
            "fixed_income_strategist",
            "esg_analyst",
            "industry_researcher",
            "quant_researcher",
            "trade_executor",
            "risk_officer",
            "portfolio_risk_manager",
            "chief_investment_officer",
        ],
        data_requirements=["quote", "fundamental", "technicals", "macro_news", "sentiment", "fed_watch"],
        chief_prompt_file="chief_analyst.md",
    ),
    "earnings_watch": ScenarioTemplate(
        id="earnings_watch",
        name="财报季快评",
        domain="finance",
        description="财报发布前后快评：预期差识别、催化与风险、财报后走势推演",
        expert_ids=[
            "fundamental_analyst",
            "event_driven_analyst",
            "valuation_expert",
            "technical_analyst",
            "news_analyst",
            "risk_officer",
        ],
        data_requirements=["quote", "fundamental", "technicals", "macro_news", "sentiment"],
        chief_prompt_file="chief_analyst.md",
    ),
    "macro_allocation": ScenarioTemplate(
        id="macro_allocation",
        name="宏观资产配置",
        domain="finance",
        description="跨资产（股/债/商品/汇率）配置视角：宏观周期 + 利率 + 情绪 + 风控 + 首席收敛（无需绑定个股）",
        expert_ids=[
            "macro_strategist",
            "fixed_income_strategist",
            "sentiment_analyst",
            "quant_researcher",
            "portfolio_risk_manager",
            "chief_investment_officer",
        ],
        data_requirements=["macro_news", "sentiment", "fed_watch", "market_review"],
        chief_prompt_file="chief_analyst.md",
    ),
    "event_special": ScenarioTemplate(
        id="event_special",
        name="事件驱动专项",
        domain="finance",
        description="针对单一催化事件（并购/政策/行业突变）的快速专项研判：事件定性 + 定价 + 执行 + 风控",
        expert_ids=[
            "event_driven_analyst",
            "news_analyst",
            "fundamental_analyst",
            "technical_analyst",
            "options_strategist",
            "trade_executor",
            "risk_officer",
        ],
        data_requirements=["quote", "fundamental", "technicals", "macro_news", "sentiment"],
        chief_prompt_file="chief_analyst.md",
    ),
    "trading_decision": ScenarioTemplate(
        id="trading_decision",
        name="交易决策",
        domain="finance",
        description="聚焦交易执行层面：择时 + 仓位 + 风控 + 情绪判断",
        expert_ids=[
            "technical_analyst",
            "sentiment_analyst",
            "quant_researcher",
            "trade_executor",
            "portfolio_risk_manager",
        ],
        data_requirements=["quote", "technicals", "sentiment"],
        chief_prompt_file="chief_analyst.md",
    ),
    "code_review": ScenarioTemplate(
        id="code_review",
        name="代码审查",
        domain="code",
        description="多视角代码审查：架构 + 安全 + 性能 + 可维护性",
        expert_ids=[
            "code_architect",
            "security_expert",
            "performance_expert",
            "maintainability_expert",
        ],
        data_requirements=["code_context"],
        chief_prompt_file="chief_analyst.md",
    ),
}


def get_scenario(scenario_id: str) -> ScenarioTemplate:
    """获取场景模板"""
    template = SCENARIO_TEMPLATES.get(scenario_id)
    if not template:
        raise ValueError(f"未知场景 ID: {scenario_id}，可用: {list(SCENARIO_TEMPLATES.keys())}")
    return template


def list_scenarios() -> list[ScenarioTemplate]:
    """列出所有可用场景"""
    return list(SCENARIO_TEMPLATES.values())


def instantiate_expert_team(scenario_id: str) -> list[ExpertRole]:
    """根据场景模板实例化专家团"""
    template = get_scenario(scenario_id)
    return [get_expert(eid) for eid in template.expert_ids]
