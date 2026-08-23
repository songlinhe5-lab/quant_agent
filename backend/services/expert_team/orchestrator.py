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
        # 💡 COPILOT-05: 保留最近一次辩论的 session 引用，供 service 层持久化
        self._last_session: Optional[DebateSession] = None

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

            # ─── 阶段 1: 查询标的 + 采集共享数据（逐步透传，供前端折叠思考过程展示）────
            session.status = "collecting"
            yield StreamEvent(type="status", message="正在查询标的并采集数据...")

            # 第一步：查询标的 —— 展示解析结果（已绑定/自动解析/未识别）
            yield StreamEvent(
                type="data_collect",
                message="查询标的",
                data={
                    "key": "查询标的",
                    "status": "success" if ticker else "error",
                    "message": f"标的: {ticker}" if ticker else "未识别到标的，无法采集个股数据",
                    "response": ticker or None,
                },
            )

            # 用队列接收 collect_shared_data 内部逐步完成的数据项，边采边 yield data_collect 事件
            progress_q: "asyncio.Queue[dict[str, Any]]" = asyncio.Queue()

            async def _report(item: dict[str, Any]) -> None:
                await progress_q.put(item)

            collect_task = asyncio.create_task(
                collect_shared_data(
                    data_requirements=template.data_requirements,
                    tool_registry=self.tool_registry,
                    ticker=ticker,
                    code_context=code_context,
                    extra_context=extra_context,
                    on_progress=_report,
                )
            )

            while not collect_task.done() or not progress_q.empty():
                try:
                    item = await asyncio.wait_for(progress_q.get(), timeout=0.3)
                    yield StreamEvent(
                        type="data_collect",
                        message=f"采集 {item.get('key')}: {item.get('status')}",
                        data={
                            "key": item.get("key"),
                            "status": item.get("status"),
                            "message": item.get("message", ""),
                            # 协议请求/响应内容（供前端折叠展示）
                            "request": item.get("request"),
                            "response": item.get("response"),
                        },
                    )
                except asyncio.TimeoutError:
                    # 无新进度，等待采集任务完成
                    await asyncio.sleep(0.05)

            shared_data = await collect_task
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
            self._last_session = session  # 💡 COPILOT-05: 暴露给 service 持久化

            yield StreamEvent(
                type="done",
                message="专家团研判完成",
                data={"session_id": session.session_id},
            )

        except Exception as e:
            session.status = "error"
            session.error_message = str(e)
            session.completed_at = datetime.now(timezone.utc).isoformat()
            self._last_session = session  # 💡 COPILOT-05: 错误状态也持久化
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
        """把文本切成小片段 (按句子/换行优先, 超长无标点硬切), 制造打字机效果"""
        import re

        if not text:
            return [""]
        raw = re.split(r"(?<=[。！？!?\n])", text)
        chunks: list[str] = []
        buf = ""
        for seg in raw:
            if not seg:
                continue
            buf += seg
            # 缓冲达阈值: 先按 max_chunk 硬切已累积部分, 余下继续累积
            while len(buf) >= max_chunk:
                chunks.append(buf[:max_chunk])
                buf = buf[max_chunk:]
        if buf:
            chunks.append(buf)
        return chunks or [text]

    @staticmethod
    def _shared_data_missing(shared_text: str) -> bool:
        """检测共享数据包是否大面积缺失（所有数据源不可用）。

        当 collect_shared_data 各 section 返回 status=error/skipped/timeout 时，
        format_shared_data_for_prompt 会拼成 `[数据不可用: ...]`。若占比过高视为数据缺失。
        """
        if not shared_text or len(shared_text) < 50:
            return True
        missing = shared_text.count("[数据不可用") + shared_text.count("[数据缺失") + shared_text.count("无可用数据")
        # 粗略：出现 ≥3 处缺失标记或缺失密度高，视为数据缺失
        return missing >= 3 or (missing >= 1 and missing / max(shared_text.count("## "), 1) >= 0.5)

    @staticmethod
    async def _generate_with_retry(
        llm_call,
        retries: int = 2,
    ) -> Any:
        """对 generate_pydantic 加简单重试：JSON 被截断/解析失败时重试，成功即返回。"""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await llm_call()
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(0.6 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _parse_text_fallback(text: str, round_index: int) -> ExpertOpinion:
        """纯文本降级：从 LLM 自由文本中尽力解析 stance/confidence，避免把报错串当观点。

        解析不到时用保守默认（置信度 0 + 明确"无法判断"），绝不暴露底层报错给用户。
        """
        import re as _re

        stance = "数据不足，无法给出明确研判，建议等待数据补充后再作判断。"
        confidence = 0
        evidence: list[str] = []
        reasoning = text.strip()[:500] if text else ""

        m = _re.search(r"置信度[：:\s]*(\d{1,3})", text)
        if m:
            try:
                confidence = min(max(int(m.group(1)), 0), 100)
            except ValueError:
                confidence = 0
        m2 = _re.search(r"[【\[]?(核心观点|观点|立场|判断)[】\]】?[：:\s]*(.{5,200})", text)
        if m2:
            stance = m2.group(2).strip()[:200]

        return ExpertOpinion(
            expert_id="unknown",
            round=round_index,
            stance=stance,
            confidence=confidence,
            key_evidence=evidence,
            reasoning=reasoning,
        )

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
                # FIX: 不把底层报错串当观点暴露给用户，返回明确的"无法判断"
                opinions.append(
                    ExpertOpinion(
                        expert_id=expert.id,
                        round=1,
                        stance="数据不足或模型输出异常，本轮无法形成有效研判，建议待数据补充后再作判断。",
                        confidence=0,
                    )
                )
            elif result is not None:
                opinions.append(result)

        return opinions

    async def _call_expert_round1(self, expert: ExpertRole, question: str, shared_text: str) -> Optional[ExpertOpinion]:
        """单个专家的 Round 1 调用"""
        system_prompt = expert.system_prompt or f"你是{expert.name}，{expert.description}。"

        # PERF/FIX: 数据缺失时强制压低置信度，禁止基于行业常识硬给方向性高置信判断
        data_missing = self._shared_data_missing(shared_text)
        confidence_rule = (
            "\n\n⚠️ 注意：以上共享数据包存在大面积缺失/不可用。此时你的判断缺乏数据支撑，"
            "请严格遵守：confidence 必须 ≤ 30，且 stance 只做审慎的定性风险提示，明确声明'数据不足，不构成配置建议'，"
            "绝不可给出高置信度的多空判断。"
            if data_missing
            else ""
        )

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
{confidence_rule}
注意：你正在独立研判，看不到其他专家的观点。请基于数据和你的专业视角给出判断。"""

        try:
            result = await asyncio.wait_for(
                self._generate_with_retry(
                    lambda: llm_service.generate_pydantic(
                        prompt=user_prompt,
                        response_model=_Round1Output,
                        system_prompt=system_prompt,
                        tier=ModelTier.STANDARD,
                        temperature=0.3,
                    )
                ),
                timeout=_EXPERT_TIMEOUT,
            )
            # 数据缺失时，即便 LLM 违反规则给出高置信，也强制压低到 30
            conf = min(result.confidence, 30) if data_missing else result.confidence
            return ExpertOpinion(
                expert_id=expert.id,
                round=1,
                stance=result.stance,
                confidence=conf,
                key_evidence=result.key_evidence,
                reasoning=result.reasoning,
            )
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] {expert.id} Round1 超时 ({_EXPERT_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"⚠️ [Orchestrator] {expert.id} Round1 结构化失败，降级为纯文本: {e}")
            # P0: 结构化校验失败 → 纯文本降级，避免把报错串当观点
            try:
                raw = await asyncio.wait_for(
                    llm_service.generate(
                        user_prompt=user_prompt,
                        system_prompt=system_prompt,
                        tier=ModelTier.STANDARD,
                        temperature=0.3,
                    ),
                    timeout=_EXPERT_TIMEOUT,
                )
                fallback = self._parse_text_fallback(raw or "", 1)
                fallback.expert_id = expert.id
                if data_missing:
                    fallback.confidence = min(fallback.confidence, 30)
                return fallback
            except Exception as e2:  # noqa: BLE001
                print(f"⚠️ [Orchestrator] {expert.id} Round1 纯文本降级也失败: {e2}")
                # 返回明确"无法判断"，绝不外泄底层报错
                return ExpertOpinion(
                    expert_id=expert.id,
                    round=1,
                    stance="数据不可用且模型输出异常，本轮无法形成有效研判。",
                    confidence=0,
                    reasoning="",
                )

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
                # FIX: 不把底层报错串当观点暴露给用户
                opinions.append(
                    ExpertOpinion(
                        expert_id=expert.id,
                        round=2,
                        stance="交叉辩论阶段数据或模型输出异常，本轮无法形成有效研判。",
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

        # FIX: 数据缺失时禁止在交叉辩论中把置信度上调，且新论点必须可验证
        data_missing = self._shared_data_missing(shared_text)
        confidence_rule = (
            "\n\n⚠️ 注意：以上共享数据包存在大面积缺失/不可用。此时："
            "confidence 必须 ≤ 30 且不得上调（confidence_delta 须 ≤ 0）；"
            "若其他专家在缺数据下给出高置信度，你应在 challenges 中明确指出其依据不足，而非跟随上调。"
            if data_missing
            else ""
        )

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
}}
{confidence_rule}"""

        try:
            result = await asyncio.wait_for(
                self._generate_with_retry(
                    lambda: llm_service.generate_pydantic(
                        prompt=user_prompt,
                        response_model=_Round2Output,
                        system_prompt=system_prompt,
                        tier=ModelTier.STANDARD,
                        temperature=0.4,
                    )
                ),
                timeout=_EXPERT_TIMEOUT,
            )
            # 数据缺失时：置信度强制 ≤30，且不允许上调（confidence_delta 截为 ≤0）
            conf = result.confidence
            conf_delta = result.confidence_delta
            if data_missing:
                conf = min(conf, 30)
                conf_delta = min(conf_delta, 0)
            return ExpertOpinion(
                expert_id=expert.id,
                round=2,
                stance=result.stance,
                confidence=conf,
                key_evidence=result.key_evidence,
                reasoning=result.reasoning,
                challenges=result.challenges,
                confidence_delta=conf_delta,
                revised_stance=result.revised_stance,
            )
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] {expert.id} Round2 超时 ({_EXPERT_TIMEOUT}s)")
            return None
        except Exception as e:
            print(f"⚠️ [Orchestrator] {expert.id} Round2 结构化失败，降级为纯文本: {e}")
            # P0: 结构化校验失败 → 纯文本降级，避免把报错串当观点
            try:
                raw = await asyncio.wait_for(
                    llm_service.generate(
                        user_prompt=user_prompt,
                        system_prompt=system_prompt,
                        tier=ModelTier.STANDARD,
                        temperature=0.4,
                    ),
                    timeout=_EXPERT_TIMEOUT,
                )
                fallback = self._parse_text_fallback(raw or "", 2)
                fallback.expert_id = expert.id
                if data_missing:
                    fallback.confidence = min(fallback.confidence, 30)
                return fallback
            except Exception as e2:  # noqa: BLE001
                print(f"⚠️ [Orchestrator] {expert.id} Round2 纯文本降级也失败: {e2}")
                return ExpertOpinion(
                    expert_id=expert.id,
                    round=2,
                    stance="数据不可用且模型输出异常，本轮无法形成有效研判。",
                    confidence=0,
                    reasoning="",
                )

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

        # FIX: 数据缺失时，首席概率评估应收敛到"不确定"区间，避免伪精确
        data_missing = False
        try:
            shared_text_for_check = format_shared_data_for_prompt(session.shared_data or {})
            data_missing = self._shared_data_missing(shared_text_for_check)
        except Exception:  # noqa: BLE001
            data_missing = False
        probability_rule = (
            "\n\n⚠️ 注意：本轮共享数据包存在大面积缺失/不可用，所有专家的判断均缺乏数据支撑。"
            "因此 probability_assessment 应收敛到 40-60 的'高度不确定'区间，并在 full_report 中明确声明"
            "'因数据不足，本概率仅为低置信度的情景判断，不构成量化结论'，不可给出远离 50 的精确概率。"
            if data_missing
            else ""
        )

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
}}
{probability_rule}"""

        chief_system = (
            "你是一位资深首席分析师，负责综合多位专家的研判结果，"
            "识别共识与分歧，权衡各方论据强度，给出最终概率评估和投资建议。"
            "你的判断应当客观、全面，既尊重多数派共识，也保留有价值的少数派意见。"
        )

        try:
            result = await asyncio.wait_for(
                self._generate_with_retry(
                    lambda: llm_service.generate_pydantic(
                        prompt=user_prompt,
                        response_model=ChiefReport,
                        system_prompt=chief_system,
                        tier=ModelTier.FLAGSHIP,
                        temperature=0.2,
                    )
                ),
                timeout=_EXPERT_TIMEOUT,
            )
            # 数据缺失时兜底：即便 LLM 违反规则，也把概率收敛到 40-60 不确定区间
            if data_missing and result.probability_assessment is not None:
                result.probability_assessment = min(max(result.probability_assessment, 40), 60)
            return result
        except Exception as e:  # noqa: BLE001
            # FIX: 首席收敛必须降级，绝不能抛异常中断整个辩论 SSE 流（前端会显示"辩论流程异常"）。
            print(f"⚠️ [Orchestrator] 首席收敛结构化失败，降级为纯文本: {e}")
            try:
                raw = await asyncio.wait_for(
                    llm_service.generate(
                        user_prompt=user_prompt,
                        system_prompt=chief_system,
                        tier=ModelTier.FLAGSHIP,
                        temperature=0.2,
                    ),
                    timeout=_EXPERT_TIMEOUT,
                )
                text = (raw or "").strip()
                if text:
                    # 尽力从纯文本解析关键字段；解析不到就用整段作为 full_report
                    import re as _re

                    m_prob = _re.search(r"(\d{1,3})\s*%", text)
                    prob = int(m_prob.group(1)) if m_prob else 50
                    prob = min(max(prob, 0), 100)
                    if data_missing:
                        prob = min(max(prob, 40), 60)
                    return ChiefReport(
                        probability_assessment=prob,
                        final_recommendation=text[:300],
                        full_report=text,
                        risk_warnings=[],
                        minority_opinion="",
                        consensus_areas=[],
                        divergence_areas=[],
                        strongest_bull_case="",
                        strongest_bear_case="",
                    )
            except Exception as e2:  # noqa: BLE001
                print(f"⚠️ [Orchestrator] 首席收敛纯文本降级也失败: {e2}")
            # 最终兜底：返回明确"收敛失败"的最简报告，仍不中断流程
            return ChiefReport(
                probability_assessment=50,
                final_recommendation="首席收敛报告生成异常，无法给出明确结论，建议稍后重试。",
                full_report="> ⚠️ 首席收敛报告生成异常，本轮无法完成最终研判。请稍后重试。",
                risk_warnings=["模型输出异常，未能生成完整收敛报告"],
                minority_opinion="",
                consensus_areas=[],
                divergence_areas=[],
                strongest_bull_case="",
                strongest_bear_case="",
            )


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
