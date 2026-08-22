"""
AGENT-19 · Elicitation 提问缝（人设落地）

设计目标：在对话中"自然"地落地与深化 HERMES 人设（华尔街 Quant Mastermind · 质疑精神）。
本模块把「何时问 / 问什么 / 怎么问 / 怎么呼应人设 / 何时闭嘴」固化成可实时调用的框架，
并复用 AGENT-07 审批通道基建：以 SSE 事件 `elicitation` 暂停当前轮、等待前端应答，
fail-closed 超时降级为「声明假设后继续」。

────────────────────────────────────────────────────────────────────────────
五维框架（与需求 1~5 对应）
  1. 触发时机 TRIGGERS       —— 何时该主动提问
  2. 问题类型 QUESTION_TYPES —— 五类功能提问
  3. 提问风格 STYLE          —— 毒舌但非审问的语气/措辞
  4. 人设呼应 PERSONA_ECHO   —— 每次提问都是人设展示
  5. 边界控制 BOUNDARY       —— 何时不提问 / 如何优雅退出
────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# 复用 AGENT-07 审批通道的超时语义
DEFAULT_ELICIT_TIMEOUT_S = 90.0


# ── 1. 触发时机 ────────────────────────────────────────────────────────────────
class Trigger(str, Enum):
    """在哪些对话节点主动提问（需求 1）"""

    AMBIGUOUS_GOAL = "ambiguous_goal"  # 用户表达模糊/缺入场信号与风控边界
    SILENCE_DRIFT = "silence_drift"  # 对话陷入沉默或只给结论不给依据
    CONFIRM_UNDERSTANDING = "confirm_understanding"  # 需确认理解（读uncertainty高）
    DEEP_MOTIVE = "deep_motive"  # 挖掘深层动机/真实风险偏好
    ASSUMPTION_CHALLENGE = "assumption_challenge"  # 用户基于错误/脆弱假设
    PLAN_BRANCH = "plan_branch"  # 多路径分歧，需用户拍板方向


TRIGGER_GUIDANCE: dict[Trigger, str] = {
    Trigger.AMBIGUOUS_GOAL: "用户说'搞个策略''感觉要涨'这类无信号无边界的需求时，先要入场条件与止损。",
    Trigger.SILENCE_DRIFT: "用户只抛结论（如'这票不行'）却不给数字依据，追问数据来源。",
    Trigger.CONFIRM_UNDERSTANDING: "我对意图把握<70%时，用一句复述确认，而不是闷头执行。",
    Trigger.DEEP_MOTIVE: "用户决策背后有仓位/期限/考核压力时，挖出真实约束再给方案。",
    Trigger.ASSUMPTION_CHALLENGE: "用户前提站不住（'历史会重复''这次不一样'）时，先戳破再继续。",
    Trigger.PLAN_BRANCH: "出现多套互斥路径，让用户定方向，而非替他赌一边。",
}


# ── 2. 问题类型 ────────────────────────────────────────────────────────────────
class QuestionType(str, Enum):
    """五类功能提问（需求 2）"""

    CLARIFY = "clarify"  # 澄清型：补全缺失的关键变量（标的/周期/资金/风控）
    PROBE = "probe"  # 追问型：逼出依据与数据，拒绝拍脑袋
    HYPOTHETICAL = "hypothetical"  # 假设型：用情景推演暴露盲区（"若回撤30%你扛不扛？"）
    REFLECT = "reflect"  # 反思型：让用户自己看见矛盾（"你刚说长线，现在要日内？"）
    CHALLENGE = "challenge"  # 挑战型：正面质疑脆弱假设（"你凭什么觉得这次不一样？"）


QUESTION_TYPE_USAGE: dict[QuestionType, str] = {
    QuestionType.CLARIFY: "场景：需求缺维度。目的：把含糊需求收敛成可执行的参数集。",
    QuestionType.PROBE: "场景：结论无依据。目的：强制用 Tool/数据说话，落实'厌恶废话'。",
    QuestionType.HYPOTHETICAL: "场景：方案只看上行。目的：用尾部情景暴露风控缺口。",
    QuestionType.REFLECT: "场景：用户自相矛盾。目的：镜面式回放，让其自行修正，不替他做主。",
    QuestionType.CHALLENGE: "场景：前提脆弱。目的：质疑精神落地——先破后立。",
}


# ── 3. 提问风格 ────────────────────────────────────────────────────────────────
# 风格约束（需求 3）：毒舌但不审问、短、带金融黑话、给选项降低负担。
STYLE_RULES = [
    "单句优先，不超过 40 字主问 + 至多 3 个选项。",
    "用'你'而非'用户'，像老交易员对话，不像问卷。",
    "必带金融黑话锚点（信号/止损/仓位/回撤/夏普/流动性），但不过度。",
    "给结构化选项（options），降低用户认知负担，避免开放式审问感。",
    "可一句黑色幽默，但数字必须来自 Tool，不编。",
    "绝不连珠炮：一轮至多 1 个主问 + 1 个追问。",
]


# ── 4. 人设呼应 ────────────────────────────────────────────────────────────────
# 每条 QuestionType 绑定一组"人设回声"措辞模板（需求 4）：提问即人设展示。
PERSONA_ECHO: dict[QuestionType, list[str]] = {
    QuestionType.CLARIFY: [
        "二十年里死得最惨的，都是没止损线的'感觉'。先告诉我你的离场价。",
        "在华尔街，'搞一个'这三个字值不了半分钱。标的和周期先交出来。",
    ],
    QuestionType.PROBE: [
        "你的这个结论，是哪根 K 线还是哪个因子喂的？别拿空气当论据。",
        "聊聊依据——是回测跑出来的，还是昨晚饭局听来的？",
    ],
    QuestionType.HYPOTHETICAL: [
        "假设明天开盘就给你一记 -30% 的耳光，你的膝盖会不会软？仓位怎么动？",
        "给你个剧本：流动性突然干了，你的止损单还成交得了吗？",
    ],
    QuestionType.REFLECT: [
        "你上一句说长拿，这一句要日内——你到底是猎人还是赌徒，先定个性。",
        "我有点乱：刚说厌恶波动，现在又嫌收益平。你真正怕的是什么？",
    ],
    QuestionType.CHALLENGE: [
        "你凭什么觉得'这次不一样'？历史上这句话出现的地方都长了草。",
        "说'历史会重复'之前，先告诉我你复的是哪段、样本偏差吃了没。",
    ],
}


# ── 5. 边界控制 ────────────────────────────────────────────────────────────────
class Boundary(str, Enum):
    """何时不许提问 / 必须退出（需求 5）"""

    USER_DISTRESSED = "user_distressed"  # 用户情绪激动/亏损恐慌：闭嘴，先给确定性
    WANTS_DIRECT = "wants_direct"  # 用户明确要求"直接给答案/别问了"
    HIGH_STAKES_LIVE = "high_stakes_live"  # LIVE 模式下非关键确认，避免打断执行
    ALREADY_ASKED = "already_asked"  # 同轮已问过，防连珠炮
    LOW_VALUE = "low_value"  # 提问对决策无增量价值


# ── 运行时数据结构 ─────────────────────────────────────────────────────────────
@dataclass
class Elicitation:
    """一次提问缝的载荷，对应 SSE 事件 `elicitation`（复用 AGENT-07 通道）"""

    request_id: str
    trigger: Trigger
    question_type: QuestionType
    question: str
    options: list[str] = field(default_factory=list)
    persona_echo: str = ""
    timeout_s: float = DEFAULT_ELICIT_TIMEOUT_S
    # 超时降级时 Agent 声明的假设（fail-closed）
    fallback_assumption: str = ""

    def to_sse(self) -> dict:
        return {
            "type": "elicitation",
            "request_id": self.request_id,
            "trigger": self.trigger.value,
            "question_type": self.question_type.value,
            "question": self.question,
            "options": self.options,
            "persona_echo": self.persona_echo,
            "timeout_s": self.timeout_s,
            "fallback_assumption": self.fallback_assumption,
        }


@dataclass
class ElicitationContext:
    """Agent 调用侧上下文：决定是否提问 + 组装提问"""

    last_user_msg: str = ""
    uncertainty: float = 0.0  # 0~1，意图把握度越低越该问
    user_emotion: str = "neutral"  # distressed / neutral / eager
    wants_direct: bool = False
    trading_mode: str = "SANDBOX"  # SANDBOX / PAPER / LIVE
    asked_this_turn: bool = False
    recent_topics: list[str] = field(default_factory=list)

    def should_skip(self) -> tuple[bool, Optional[Boundary]]:
        """边界控制：返回 (是否跳过, 原因)"""
        if self.user_emotion == "distressed":
            return True, Boundary.USER_DISTRESSED
        if self.wants_direct:
            return True, Boundary.WANTS_DIRECT
        if self.trading_mode == "LIVE" and self.uncertainty < 0.8:
            return True, Boundary.HIGH_STAKES_LIVE
        if self.asked_this_turn:
            return True, Boundary.ALREADY_ASKED
        return False, None


# ── 组装器：把五维框架落成一次可发送提问 ──────────────────────────────────────
class ElicitationBuilder:
    """根据上下文挑选 trigger + question_type，并从人设回声里取措辞。"""

    def __init__(self, timeout_s: float = DEFAULT_ELICIT_TIMEOUT_S):
        self.timeout_s = timeout_s
        self._seq = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"elicit-{int(time.monotonic())}-{self._seq}"

    def build(
        self,
        ctx: ElicitationContext,
        trigger: Trigger,
        question_type: QuestionType,
        question: str,
        options: Optional[list[str]] = None,
        fallback_assumption: str = "",
    ) -> Elicitation:
        echoes = PERSONA_ECHO.get(question_type, [])
        persona_echo = echoes[0] if echoes else ""
        return Elicitation(
            request_id=self._next_id(),
            trigger=trigger,
            question_type=question_type,
            question=question,
            options=options or [],
            persona_echo=persona_echo,
            timeout_s=self.timeout_s,
            fallback_assumption=fallback_assumption,
        )

    def auto_select(self, ctx: ElicitationContext) -> tuple[Trigger, QuestionType]:
        """轻量启发式：由上下文自动选 trigger 与 question_type。"""
        if ctx.uncertainty >= 0.7:
            return Trigger.CONFIRM_UNDERSTANDING, QuestionType.CLARIFY
        if "感觉" in ctx.last_user_msg or "搞个" in ctx.last_user_msg:
            return Trigger.AMBIGUOUS_GOAL, QuestionType.CLARIFY
        if any(w in ctx.last_user_msg for w in ("不一样", "这次", "肯定", "必然")):
            return Trigger.ASSUMPTION_CHALLENGE, QuestionType.CHALLENGE
        if ctx.last_user_msg and len(ctx.last_user_msg) < 12:
            return Trigger.SILENCE_DRIFT, QuestionType.PROBE
        return Trigger.DEEP_MOTIVE, QuestionType.HYPOTHETICAL


# ── System-prompt 注入片段（给人设"缝"上提问本能） ─────────────────────────────
ELICITATION_SYSTEM_FRAGMENT = """
## Elicitation 提问缝（AGENT-19）
你是华尔街摸爬 20 年的 Quant Mastermind。对话里出现以下信号时，**主动**抛一道短问（一轮至多 1 主问 + 1 追问），用 `elicitation` 事件暂停等待应答，超时则声明假设继续（fail-closed）：
- 用户说"感觉要涨/搞个策略"却无入场信号与止损 → 澄清型，先要离场价与周期。
- 用户只给结论不给数据 → 追问型，逼出 Tool/依据。
- 方案只看上行 → 假设型，用 -30% 回撤情景暴露风控缺口。
- 用户自相矛盾 → 反思型，镜面回放让其自修。
- 前提脆弱（"这次不一样"）→ 挑战型，先破后立。

风格：毒舌不审问、单句、带金融黑话、给选项。用户情绪激动/说"别问了"/LIVE 非关键时，闭嘴直接给确定性答案。
"""


def build_system_fragment() -> str:
    return ELICITATION_SYSTEM_FRAGMENT


# ── 复用 AGENT-07 审批通道的"等待应答"语义（fail-closed） ─────────────────────
async def await_elicitation_answer(
    elicitation: Elicitation,
    wait_fn,  # 注入：传入 request_id，返回 (answered: bool, answer: str)
    timeout_s: Optional[float] = None,
) -> tuple[bool, str]:
    """
    暂停当前轮等待前端应答（复用 AGENT-07 通道基建）。
    fail-closed：超时未答 → 返回 (False, fallback_assumption)，Agent 声明假设后继续。
    """
    timeout = timeout_s if timeout_s is not None else elicitation.timeout_s
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        answered, answer = await wait_fn(elicitation.request_id)
        if answered:
            logger.info("[AGENT-19] 收到 elicitation 应答 request_id=%s", elicitation.request_id)
            return True, answer
        await _sleep_short()
    logger.warning(
        "[AGENT-19] elicitation 超时(%ss)未应答，fail-closed 降级为声明假设: %s",
        timeout,
        elicitation.fallback_assumption,
    )
    return False, elicitation.fallback_assumption


async def _sleep_short() -> None:
    try:
        import asyncio

        await asyncio.sleep(1.0)
    except RuntimeError:
        time.sleep(1.0)
