"""
三轮混合协议编排引擎 (核心)
Round 1: 独立研判 (并行) → Round 2: 交叉辩论 (对抗) → Round 3: 首席收敛 (综合)
"""

import asyncio
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from backend.services.ai_narrator.llm_service import ModelTier, llm_service
from backend.services.expert_team.data_collector import (
    collect_shared_data,
    format_shared_data_for_prompt,
)
from backend.services.expert_team.expert_registry import (
    get_scenario,
    instantiate_expert_team,
)
from backend.services.expert_team.models import (
    ChiefReport,
    DebateSession,
    ExpertOpinion,
    ExpertRole,
    StreamEvent,
)
from hermes_agent.tool_registry import ToolRegistry

# ─── 超时配置 ──────────────────────────────────────────────────
_EXPERT_TIMEOUT = 60.0  # 单个专家超时
_ROUND_TIMEOUT = 180.0  # 整轮超时


class DebateOrchestrator:
    """三轮辩论编排引擎"""

    def __init__(self, tool_registry: Optional[ToolRegistry] = None):
        self.tool_registry = tool_registry

    async def run_debate_stream(
        self,
        scenario_id: str,
        question: str,
        ticker: Optional[str] = None,
        code_context: Optional[str] = None,
        extra_context: Optional[dict[str, Any]] = None,
        rounds: int = 2,
        expert_ids: Optional[list[str]] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        执行完整辩论流程，以 SSE 事件流输出进度。

        Args:
            rounds: 辩论轮数 (1=仅独立研判; 2=独立+交叉辩论; 3-4=多轮交叉深化)
            expert_ids: 自定义专家阵容 (覆盖场景默认阵容); 为空则用场景默认

        Yields:
            StreamEvent: 各阶段进度事件
        """
        session = DebateSession(
            session_id=str(uuid.uuid4())[:8],
            scenario=scenario_id,
            question=question,
            context={"ticker": ticker, "code_context": code_context is not None, "rounds": rounds},
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # ─── 阶段 0: 初始化专家团 ───────────────────────────
            template = get_scenario(scenario_id)
            if expert_ids:
                # 自定义阵容: 按传入顺序实例化 (保留 scenario 的 data_requirements/chief_prompt)
                from backend.services.expert_team.expert_registry import get_expert

                experts = [get_expert(eid) for eid in expert_ids]
            else:
                experts = instantiate_expert_team(scenario_id)
            session.experts = experts

            yield StreamEvent(
                type="status",
                message=f"专家团已组建: {', '.join(e.name for e in experts)}"
                + (f" · {rounds} 轮辩论" if rounds > 1 else " · 单轮研判"),
                data={"experts": [e.model_dump() for e in experts], "rounds": rounds},
            )

            # ─── 阶段 1: 采集共享数据 ──────────────────────────
            session.status = "collecting"
            yield StreamEvent(type="status", message="正在采集共享数据包...")

            shared_data = await collect_shared_data(
                data_requirements=template.data_requirements,
                tool_registry=self.tool_registry,
                ticker=ticker,
                code_context=code_context,
                extra_context=extra_context,
            )
            session.shared_data = shared_data

            yield StreamEvent(
                type="status",
                message=f"数据采集完成: {len(shared_data)} 项",
                data={"collected_keys": list(shared_data.keys())},
            )

            # ─── 阶段 2: Round 1 独立研判 ──────────────────────
            session.status = "round1"
            yield StreamEvent(type="status", message="Round 1: 各专家独立研判中...")

            shared_text = format_shared_data_for_prompt(shared_data)
            round1_opinions = await self._run_round1(session, experts, question, shared_text)
            session.round1_opinions = round1_opinions

            for opinion in round1_opinions:
                async for ev in self._yield_opinion_stream(opinion, round_index=1):
                    yield ev

            yield StreamEvent(
                type="round_complete",
                message="Round 1 完成",
                data={"round": 1, "opinion_count": len(round1_opinions)},
            )

            # ─── 阶段 3: Round 2..N 交叉辩论 (多轮深化) ────────
            latest_opinions = round1_opinions
            for r in range(2, rounds + 1):
                session.status = f"round{r}"
                yield StreamEvent(type="status", message=f"Round {r}: 交叉辩论中...")

                round_opinions = await self._run_round2(session, experts, question, shared_text, latest_opinions)
                # 用本轮输出覆盖上一轮 (便于合成阶段读取最新观点)
                self._promote_round(session, round_opinions, round_index=r)
                latest_opinions = round_opinions

                for opinion in round_opinions:
                    async for ev in self._yield_opinion_stream(opinion, round_index=r):
                        yield ev

                yield StreamEvent(
                    type="round_complete",
                    message=f"Round {r} 完成",
                    data={"round": r, "opinion_count": len(round_opinions)},
                )

            # ─── 阶段 4: 首席收敛 ─────────────────────────────
            session.status = "synthesis"
            yield StreamEvent(type="status", message="首席分析师正在收敛最终报告...")

            chief_report = await self._run_synthesis(session, question, round1_opinions, latest_opinions)
            session.chief_report = chief_report

            yield StreamEvent(
                type="chief_report",
                message="首席分析师报告完成",
                content=chief_report.full_report,
                data=chief_report.model_dump(),
            )

            # ─── 完成 ─────────────────────────────────────────
            session.status = "done"
            session.completed_at = datetime.now(timezone.utc).isoformat()

            yield StreamEvent(
                type="done",
                message="专家团研判完成",
                data={"session_id": session.session_id},
            )

        except Exception as e:
            session.status = "error"
            session.error_message = str(e)
            print(f"❌ [Orchestrator] 辩论异常: {e}\n{traceback.format_exc()}")
            yield StreamEvent(
                type="error",
                message=f"辩论流程异常: {str(e)}",
                data={"session_id": session.session_id},
            )

    # ─── 辅助方法 ─────────────────────────────────────────────

    @staticmethod
    def _opinion_to_text(opinion: ExpertOpinion) -> str:
        """把专家观点拼为人读文本 (供前端流式渲染)"""
        return "\n\n".join(DebateOrchestrator._opinion_text_parts(opinion))

    @staticmethod
    def _opinion_text_parts(opinion: ExpertOpinion) -> list[str]:
        """把专家观点拆为段落列表 (供逐段流式推送)"""
        parts: list[str] = [f"**核心观点**: {opinion.stance}"]
        if opinion.key_evidence:
            parts.append("**关键依据**:\n- " + "\n- ".join(opinion.key_evidence))
        if opinion.reasoning:
            parts.append(f"**推理**:\n{opinion.reasoning}")
        if opinion.challenges:
            parts.append("**对其他专家的质疑**:\n- " + "\n- ".join(opinion.challenges))
        if opinion.revised_stance:
            parts.append(f"**修正后观点**: {opinion.revised_stance}")
        parts.append(f"*置信度: {opinion.confidence}*")
        return parts

    @staticmethod
    def _split_for_stream(text: str, max_chunk: int = 80) -> list[str]:
        """把文本切成小片段 (按句子/换行), 制造打字机效果, 避免单次大块推送"""
        import re

        raw = re.split(r"(?<=[。！？!?\n])", text)
        chunks: list[str] = []
        buf = ""
        for seg in raw:
            if not seg:
                continue
            buf += seg
            if len(buf) >= max_chunk:
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
        return chunks or [text]

    async def _yield_opinion_stream(
        self, opinion: ExpertOpinion, round_index: int
    ) -> "AsyncGenerator[StreamEvent, None]":
        """把单个专家观点切成多片流式 yield (首片带完整 data, 后续仅增量 content)"""
        full_text = self._opinion_to_text(opinion)
        parts = self._split_for_stream(full_text)
        for i, chunk in enumerate(parts):
            yield StreamEvent(
                type="expert_opinion",
                message=f"{opinion.expert_id} 撰写中 ({i + 1}/{len(parts)})",
                # 首片附带完整结构化数据 + 完整文本, 后续片仅增量 content
                content=chunk,
                data=opinion.model_dump() if i == 0 else {},
            )

    @staticmethod
    def _promote_round(session: DebateSession, opinions: list[ExpertOpinion], round_index: int) -> None:
        """把最新一轮观点写入 session (覆盖 round2_opinions, 便于持久化展示)"""
        session.__dict__.setdefault("all_rounds", {})
        session.all_rounds[round_index] = [o.model_dump() for o in opinions]
        session.round2_opinions = opinions

    # ─── Round 1: 独立研判 ─────────────────────────────────────

    async def _run_round1(
        self,
        session: DebateSession,
        experts: list[ExpertRole],
        question: str,
        shared_text: str,
    ) -> list[ExpertOpinion]:
        """并行调度所有专家进行独立研判"""
        tasks = [self._call_expert_round1(expert, question, shared_text) for expert in experts]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_ROUND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print("⚠️ [Orchestrator] Round 1 整轮超时")
            results = []

        opinions: list[ExpertOpinion] = []
        for expert, result in zip(experts, results):
            if isinstance(result, Exception):
                print(f"⚠️ [Orchestrator] {expert.id} Round1 异常: {result}")
                opinions.append(
                    ExpertOpinion(
                        expert_id=expert.id,
                        round=1,
                        stance=f"[研判失败: {str(result)[:100]}]",
                        confidence=0,
                    )
                )
            elif result is not None:
                opinions.append(result)

        return opinions

    async def _call_expert_round1(self, expert: ExpertRole, question: str, shared_text: str) -> Optional[ExpertOpinion]:
        """单个专家的 Round 1 调用"""
        system_prompt = expert.system_prompt or f"你是{expert.name}，{expert.description}。"

        user_prompt = f"""## 用户问题
{question}

## 共享数据包
{shared_text}

## 输出要求
请以 JSON 格式输出你的独立研判：
{{
  "stance": "核心观点 (<=200字)",
  "confidence": 0-100的整数,
  "key_evidence": ["依据1", "依据2", ...],
  "reasoning": "完整推理过程"
}}

注意：你正在独立研判，看不到其他专家的观点。请基于数据和你的专业视角给出判断。"""

        try:
            result = await asyncio.wait_for(
                llm_service.generate_pydantic(
                    prompt=user_prompt,
                    response_model=_Round1Output,
                    system_prompt=system_prompt,
                    tier=ModelTier.STANDARD,
                    temperature=0.3,
                ),
                timeout=_EXPERT_TIMEOUT,
            )
            return ExpertOpinion(
                expert_id=expert.id,
                round=1,
                stance=result.stance,
                confidence=result.confidence,
                key_evidence=result.key_evidence,
                reasoning=result.reasoning,
            )
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] {expert.id} Round1 超时 ({_EXPERT_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"⚠️ [Orchestrator] {expert.id} Round1 失败: {e}")
            raise

    # ─── Round 2: 交叉辩论 ─────────────────────────────────────

    async def _run_round2(
        self,
        session: DebateSession,
        experts: list[ExpertRole],
        question: str,
        shared_text: str,
        round1_opinions: list[ExpertOpinion],
    ) -> list[ExpertOpinion]:
        """并行调度所有专家进行交叉辩论"""
        tasks = [self._call_expert_round2(expert, question, shared_text, round1_opinions) for expert in experts]

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_ROUND_TIMEOUT,
            )
        except asyncio.TimeoutError:
            print("⚠️ [Orchestrator] Round 2 整轮超时")
            results = []

        opinions: list[ExpertOpinion] = []
        for expert, result in zip(experts, results):
            if isinstance(result, Exception):
                print(f"⚠️ [Orchestrator] {expert.id} Round2 异常: {result}")
                opinions.append(
                    ExpertOpinion(
                        expert_id=expert.id,
                        round=2,
                        stance=f"[辩论失败: {str(result)[:100]}]",
                        confidence=0,
                    )
                )
            elif result is not None:
                opinions.append(result)

        return opinions

    async def _call_expert_round2(
        self,
        expert: ExpertRole,
        question: str,
        shared_text: str,
        round1_opinions: list[ExpertOpinion],
    ) -> Optional[ExpertOpinion]:
        """单个专家的 Round 2 调用"""
        system_prompt = expert.system_prompt or f"你是{expert.name}，{expert.description}。"

        # 自己的 Round 1 输出
        my_r1 = next((o for o in round1_opinions if o.expert_id == expert.id), None)
        my_r1_text = ""
        if my_r1:
            my_r1_text = f"""### 你的 Round 1 研判
- 观点: {my_r1.stance}
- 置信度: {my_r1.confidence}
- 依据: {", ".join(my_r1.key_evidence)}
- 推理: {my_r1.reasoning}"""

        # 其他专家的 Round 1 摘要
        others_text_parts: list[str] = []
        for o in round1_opinions:
            if o.expert_id != expert.id:
                others_text_parts.append(f"- **{o.expert_id}** (置信度 {o.confidence}): {o.stance}")
        others_text = "\n".join(others_text_parts)

        user_prompt = f"""## 用户问题
{question}

## 共享数据包 (摘要)
{shared_text[:3000]}

{my_r1_text}

### 其他专家的 Round 1 观点
{others_text}

## 输出要求
现在进入交叉辩论环节。请：
1. 审视其他专家的观点，找出逻辑漏洞或被忽略的风险
2. 反思自己的判断是否需要修正
3. 以 JSON 格式输出：
{{
  "stance": "修正后的核心观点 (<=200字)",
  "confidence": 0-100的整数,
  "key_evidence": ["依据1", "依据2", ...],
  "reasoning": "修正/坚持的推理过程",
  "challenges": ["对专家X的质疑: ...", ...],
  "confidence_delta": 置信度变化整数(如+5或-10),
  "revised_stance": "如果修正了观点，写修正后的观点；如果坚持，重复stance"
}}"""

        try:
            result = await asyncio.wait_for(
                llm_service.generate_pydantic(
                    prompt=user_prompt,
                    response_model=_Round2Output,
                    system_prompt=system_prompt,
                    tier=ModelTier.STANDARD,
                    temperature=0.4,
                ),
                timeout=_EXPERT_TIMEOUT,
            )
            return ExpertOpinion(
                expert_id=expert.id,
                round=2,
                stance=result.stance,
                confidence=result.confidence,
                key_evidence=result.key_evidence,
                reasoning=result.reasoning,
                challenges=result.challenges,
                confidence_delta=result.confidence_delta,
                revised_stance=result.revised_stance,
            )
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] {expert.id} Round2 超时 ({_EXPERT_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"⚠️ [Orchestrator] {expert.id} Round2 失败: {e}")
            raise

    # ─── Round 3: 首席收敛 ─────────────────────────────────────

    async def _run_synthesis(
        self,
        session: DebateSession,
        question: str,
        round1_opinions: list[ExpertOpinion],
        round2_opinions: list[ExpertOpinion],
    ) -> ChiefReport:
        """首席分析师综合所有辩论内容，生成最终报告"""
        # 组装全部辩论记录
        debate_text_parts: list[str] = []

        debate_text_parts.append("## Round 1 - 独立研判\n")
        for o in round1_opinions:
            debate_text_parts.append(
                f"### {o.expert_id} (置信度: {o.confidence})\n"
                f"观点: {o.stance}\n"
                f"依据: {', '.join(o.key_evidence)}\n"
                f"推理: {o.reasoning}\n"
            )

        debate_text_parts.append("\n## Round 2 - 交叉辩论\n")
        for o in round2_opinions:
            challenges_text = "; ".join(o.challenges) if o.challenges else "无"
            debate_text_parts.append(
                f"### {o.expert_id} (置信度: {o.confidence}, 变化: {o.confidence_delta:+d})\n"
                f"修正观点: {o.revised_stance or o.stance}\n"
                f"质疑: {challenges_text}\n"
                f"推理: {o.reasoning}\n"
            )

        debate_text = "\n".join(debate_text_parts)

        user_prompt = f"""## 用户问题
{question}

## 完整辩论记录
{debate_text}

## 输出要求
作为首席分析师，请综合所有专家的研判和辩论，输出最终收敛报告。JSON 格式：
{{
  "consensus_areas": ["共识点1", "共识点2", ...],
  "divergence_areas": ["分歧点1", "分歧点2", ...],
  "strongest_bull_case": "最强看多/正面论据",
  "strongest_bear_case": "最强看空/负面论据",
  "probability_assessment": 0-100的看涨/正面概率整数,
  "final_recommendation": "最终建议 (<=300字)",
  "risk_warnings": ["风险提示1", "风险提示2", ...],
  "minority_opinion": "少数派意见保留 (如有)",
  "full_report": "完整 Markdown 格式报告"
}}"""

        chief_system = (
            "你是一位资深首席分析师，负责综合多位专家的研判结果，"
            "识别共识与分歧，权衡各方论据强度，给出最终概率评估和投资建议。"
            "你的判断应当客观、全面，既尊重多数派共识，也保留有价值的少数派意见。"
        )

        result = await llm_service.generate_pydantic(
            prompt=user_prompt,
            response_model=ChiefReport,
            system_prompt=chief_system,
            tier=ModelTier.FLAGSHIP,
            temperature=0.2,
        )
        return result


# ─── LLM 结构化输出中间模型 ────────────────────────────────────

from pydantic import BaseModel, Field  # noqa: E402


class _Round1Output(BaseModel):
    """Round 1 LLM 输出结构"""

    stance: str
    confidence: int = Field(ge=0, le=100)
    key_evidence: list[str] = Field(default_factory=list)
    reasoning: str = ""


class _Round2Output(BaseModel):
    """Round 2 LLM 输出结构"""

    stance: str
    confidence: int = Field(ge=0, le=100)
    key_evidence: list[str] = Field(default_factory=list)
    reasoning: str = ""
    challenges: list[str] = Field(default_factory=list)
    confidence_delta: int = 0
    revised_stance: str = ""
