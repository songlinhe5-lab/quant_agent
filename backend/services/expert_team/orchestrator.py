"""
三轮混合协议编排引擎 (核心)
Round 1: 独立研判 (并行) → Round 2: 交叉辩论 (对抗) → Round 3: 首席收敛 (综合)
"""

import asyncio
import json
import time
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from pydantic import ValidationError

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
_EXPERT_TIMEOUT = 60.0  # 单个专家超时（真流式下为整段生成+限速滴播的总时限）
_ROUND_TIMEOUT = 180.0  # 整轮超时（与 _EXPERT_TIMEOUT 叠加，双保险）
_CHIEF_TIMEOUT = 120.0  # 首席报告更长，单独放宽
_STREAM_CHUNK_DELAY = 0.02  # 打字机效果：切片间隔（秒），仅降级/占位路径使用；真流式无需人造延迟
# 打字机限速（真流式）：每 _STREAM_EMIT_INTERVAL 秒最多推 _STREAM_CHARS_PER_TICK 字符，
# 防止快速模型数秒内把全文一次性砸满屏幕来不及阅读；若生成先于节奏结束，剩余缓冲按同速率滴播
_STREAM_EMIT_INTERVAL = 0.12
_STREAM_CHARS_PER_TICK = 20


class _StreamSplitter:
    """把 LLM 流分为两段：Markdown 研判文本（实时流给前端） + 末尾 ```json 结构化块（累积后解析）。

    专家/首席的输出协议：先自由研判（可流式展示），末尾以 ```json 块给出结构化字段。
    marker 可能跨 chunk 切开，故未确认前留存尾部候选前缀不先流出。
    """

    _MARKER = "```json"

    def __init__(self) -> None:
        self._pending = ""  # marker 前的研判文本缓冲（可能含半个 marker）
        self._in_json = False
        self._json_buf = ""
        self.markdown = ""

    def feed(self, chunk: str) -> str:
        """喂入增量片段，返回可实时流出的研判文本（可能为空串）"""
        if self._in_json:
            self._json_buf += chunk
            return ""
        buf = self._pending + chunk
        idx = buf.find(self._MARKER)
        if idx >= 0:
            self._in_json = True
            prose = buf[:idx]
            self._json_buf = buf[idx + len(self._MARKER) :]
            self._pending = ""
            self.markdown += prose
            return prose
        # marker 可能正在跨片段到达：留存尾部可为 marker 前缀的部分，其余先流出。
        # 从最长前缀开始匹配（含完整 marker），避免短前缀提前命中把 marker 切断
        hold = 0
        for k in range(len(self._MARKER), 0, -1):
            if buf.endswith(self._MARKER[:k]):
                hold = k
                break
        flush, self._pending = buf[: len(buf) - hold], buf[len(buf) - hold :]
        self.markdown += flush
        return flush

    def finish(self) -> tuple[str, dict]:
        """结束：冲刷剩余缓冲，去掉围栏后解析 JSON 块。
        返回 (完整 Markdown, 结构化字典)；JSON 缺失/非法时字典为空（由调用方降级）。
        """
        if self._pending:
            # 流恰好在 marker 处结束（pending 含半个/完整 marker）：同样切分，不把 marker 泄入正文
            idx = self._pending.find(self._MARKER)
            if idx >= 0:
                self.markdown += self._pending[:idx]
                self._json_buf += self._pending[idx + len(self._MARKER) :]
            else:
                self.markdown += self._pending
            self._pending = ""
        raw = self._json_buf.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        data: dict = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = {}
        return self.markdown.strip(), data


@dataclass
class _WorkerDone:
    """专家流式任务完成哨兵（携带本轮观点，供调度方归集）"""

    expert_id: str
    opinion: Optional[ExpertOpinion]


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

            # ─── 阶段 2: Round 1 独立研判（先完成先流式）────────
            session.status = "round1"
            yield StreamEvent(type="status", message="Round 1: 各专家独立研判中...")

            shared_text = format_shared_data_for_prompt(shared_data)
            round1_opinions: list[ExpertOpinion] = []
            async for ev in self._run_round_stream(experts, question, shared_text, 1, round1_opinions, None):
                yield ev
            session.round1_opinions = round1_opinions
            session.all_rounds[1] = round1_opinions

            yield StreamEvent(
                type="round_complete",
                message="Round 1 完成",
                round=1,
                data={"round": 1, "opinion_count": len(round1_opinions)},
            )

            # ─── 阶段 3: Round 2..N 交叉辩论 (多轮深化, 先完成先流式) ────
            latest_opinions = round1_opinions
            for r in range(2, rounds + 1):
                session.status = f"round{r}"
                yield StreamEvent(type="status", message=f"Round {r}: 交叉辩论中...")

                round_opinions: list[ExpertOpinion] = []
                async for ev in self._run_round_stream(
                    experts, question, shared_text, r, round_opinions, latest_opinions
                ):
                    yield ev
                # 用本轮输出覆盖上一轮 (便于合成阶段读取最新观点)
                self._promote_round(session, round_opinions, round_index=r)
                latest_opinions = round_opinions

                yield StreamEvent(
                    type="round_complete",
                    message=f"Round {r} 完成",
                    round=r,
                    data={"round": r, "opinion_count": len(round_opinions)},
                )

            # ─── 阶段 4: 首席收敛 ─────────────────────────────
            session.status = "synthesis"
            yield StreamEvent(type="status", message="首席分析师正在收敛最终报告...")

            async for ev in self._run_synthesis_stream(session, question, round1_opinions, latest_opinions):
                yield ev

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
        """把单个专家观点切成多片流式 yield (首片带完整 data, 后续仅增量 content)

        切片间插入短延迟，制造打字机效果（首片立即到达，卡片先出结构化字段）。
        """
        full_text = self._opinion_to_text(opinion)
        parts = self._split_for_stream(full_text)
        for i, chunk in enumerate(parts):
            if i > 0:
                await asyncio.sleep(_STREAM_CHUNK_DELAY)
            yield StreamEvent(
                type="expert_opinion",
                message=f"{opinion.expert_id} 撰写中 ({i + 1}/{len(parts)})",
                # 身份字段每片携带(前端据此将增量片归位到对应专家/轮次);
                # 首片附带完整结构化数据, 后续片仅增量 content
                expert_id=opinion.expert_id,
                round=round_index,
                content=chunk,
                data=opinion.model_dump() if i == 0 else {},
            )

    async def _run_round_stream(
        self,
        experts: list[ExpertRole],
        question: str,
        shared_text: str,
        round_index: int,
        out_opinions: list[ExpertOpinion],
        prev_opinions: Optional[list[ExpertOpinion]],
    ) -> "AsyncGenerator[StreamEvent, None]":
        """并行调度本轮所有专家，真·token 流边生成边推送（不等整轮也不等整篇）。

        每个专家一个 worker：把 _call_expert_roundN 生成的增量事件实时入队，
        完成后投递 _WorkerDone 哨兵（携带结构化观点）。调度方从队列消费，
        事件直接透传给上层，哨兵用于归集观点与判定占位。
        """
        q: "asyncio.Queue[Any]" = asyncio.Queue()

        async def _worker(expert: ExpertRole) -> None:
            stream = (
                self._call_expert_round1(expert, question, shared_text)
                if round_index == 1
                else self._call_expert_round2(expert, question, shared_text, prev_opinions or [])
            )
            opinion: Optional[ExpertOpinion] = None
            async for ev in stream:
                await q.put(ev)
                if ev.data and ev.data.get("expert_id") == expert.id:
                    try:
                        opinion = ExpertOpinion.model_validate(ev.data)  # 末帧结构化完成帧
                    except Exception:  # noqa: BLE001 — 校验失败不得中断调度（否则丢哨兵→整轮阻塞+占位串混入已流内容）
                        opinion = None
            await q.put(_WorkerDone(expert.id, opinion))

        tasks = [asyncio.create_task(_worker(e)) for e in experts]
        gather_task = asyncio.ensure_future(asyncio.gather(*tasks, return_exceptions=True))

        served: set[str] = set()
        deadline = asyncio.get_running_loop().time() + _ROUND_TIMEOUT

        def _consume_item(item: Any) -> Optional[StreamEvent]:
            """哨兵 → 归集观点；事件 → 透传"""
            if isinstance(item, _WorkerDone):
                served.add(item.expert_id)
                if item.opinion is not None:
                    out_opinions.append(item.opinion)
                return None
            return item

        # 按哨兵数终止；跨迭代复用同一个 get 任务（不取消）——
        # asyncio.wait_for(q.get()) 在超时瞬间可能丢已取到的条目，造成流式帧丢失（专家内容不上屏）
        remaining_sentinels = len(experts)
        get_task: Optional[asyncio.Task] = None
        try:
            while remaining_sentinels > 0:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                if get_task is None:
                    get_task = asyncio.ensure_future(q.get())
                done, _ = await asyncio.wait({get_task}, timeout=min(remaining, 0.5))
                if get_task not in done:
                    continue  # 继续等同一个 get，不取消 → 不丢条目
                item = get_task.result()
                get_task = None
                if isinstance(item, _WorkerDone):
                    remaining_sentinels -= 1
                ev = _consume_item(item)
                if ev is not None:
                    yield ev
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] Round {round_index} 整轮超时")
            gather_task.cancel()
        finally:
            if get_task is not None and not get_task.done():
                get_task.cancel()

        # 未完成/失败的专家补占位观点，保证出战阵容人人有产出（绝不泄底层报错）
        for expert in experts:
            if expert.id in served:
                continue
            placeholder = ExpertOpinion(
                expert_id=expert.id,
                round=round_index,
                stance="本轮研判超时或异常，未能在时限内产出有效观点。",
                confidence=0,
            )
            out_opinions.append(placeholder)
            async for ev in self._yield_opinion_stream(placeholder, round_index=round_index):
                yield ev

    @staticmethod
    def _promote_round(session: DebateSession, opinions: list[ExpertOpinion], round_index: int) -> None:
        """把本轮观点追加到 all_rounds（不覆盖前置轮次）；round2_opinions 承载最后一轮以兼容旧读取方"""
        session.all_rounds[round_index] = opinions
        session.round2_opinions = opinions

    # ─── Round 1: 独立研判 ─────────────────────────────────────

    async def _call_expert_round1(
        self, expert: ExpertRole, question: str, shared_text: str
    ) -> "AsyncGenerator[StreamEvent, None]":
        """单个专家的 Round 1 真流式调用：研判文本实时流出，末尾 JSON 块解析为结构化字段"""
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

## 输出要求（严格遵循，两段式）
1. 先用 Markdown 输出你的独立研判过程（核心论点、关键依据、逻辑推理、风险提示），这部分会实时流式展示给用户；
2. 然后另起一行，以 ```json 开头输出一个 JSON 代码块，仅包含以下字段：
{{
  "stance": "核心观点 (<=200字)",
  "confidence": 0-100的整数,
  "key_evidence": ["依据1", "依据2", ...]
}}
{confidence_rule}
注意：你正在独立研判，看不到其他专家的观点。请基于数据和你的专业视角给出判断。"""

        async for ev in self._stream_expert_opinion(
            expert, 1, user_prompt, system_prompt, _Round1Output, temperature=0.3, data_missing=data_missing
        ):
            yield ev

    async def _stream_expert_opinion(
        self,
        expert: ExpertRole,
        round_index: int,
        user_prompt: str,
        system_prompt: str,
        output_model: type,
        temperature: float,
        data_missing: bool,
    ) -> "AsyncGenerator[StreamEvent, None]":
        """真流式生成专家观点（round1/round2 共用骨架）。

        研判文本随 LLM token 流实时推给前端（不再是生成完再切片回放）；
        末尾 ```json 块解析后以“结构化完成帧”（content 为空、携带 data）补全观点/置信度。
        无论成败至少产出一帧完成帧，保证调度方总能归集到观点。
        """
        splitter = _StreamSplitter()
        deadline = time.monotonic() + _EXPERT_TIMEOUT
        opinion: Optional[ExpertOpinion] = None
        pending = ""
        last_emit = 0.0
        try:
            async for chunk in llm_service.generate_stream(
                user_prompt, system_prompt, tier=ModelTier.STANDARD, temperature=temperature
            ):
                if time.monotonic() > deadline:
                    raise asyncio.TimeoutError()
                prose = splitter.feed(chunk)
                if prose:
                    pending += prose
                # 打字机限速：按固定节奏推送，避免快速模型把全文瞬间刷满屏幕
                now = time.monotonic()
                if pending and (_STREAM_EMIT_INTERVAL <= 0 or now - last_emit >= _STREAM_EMIT_INTERVAL):
                    emit, pending = pending[:_STREAM_CHARS_PER_TICK], pending[_STREAM_CHARS_PER_TICK:]
                    last_emit = now
                    yield StreamEvent(type="expert_opinion", expert_id=expert.id, round=round_index, content=emit)
            # 生成先于节奏结束时，剩余缓冲按同速率滴播完毕（仍受专家超时约束）
            while pending:
                if time.monotonic() > deadline:
                    break
                await asyncio.sleep(_STREAM_EMIT_INTERVAL)
                emit, pending = pending[:_STREAM_CHARS_PER_TICK], pending[_STREAM_CHARS_PER_TICK:]
                yield StreamEvent(type="expert_opinion", expert_id=expert.id, round=round_index, content=emit)
            markdown, structured = splitter.finish()
            opinion = self._assemble_opinion(expert, round_index, markdown, structured, output_model, data_missing)
        except asyncio.TimeoutError:
            print(f"⚠️ [Orchestrator] {expert.id} Round{round_index} 流式超时 ({_EXPERT_TIMEOUT}s)")
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ [Orchestrator] {expert.id} Round{round_index} 流式生成失败: {e}")
            # 已流出部分研判文本时走文本降级提取，不丢弃已展示内容；绝不外泄底层报错
            markdown, _ = splitter.finish()
            if markdown.strip():
                opinion = self._parse_text_fallback(markdown, round_index)
                opinion.expert_id = expert.id
                opinion.reasoning = markdown[:2000]
                if data_missing:
                    opinion.confidence = min(opinion.confidence, 30)
        if opinion is None:
            opinion = ExpertOpinion(
                expert_id=expert.id,
                round=round_index,
                stance="本轮研判超时或异常，未能在时限内产出有效观点。",
                confidence=0,
            )
        # 结构化完成帧：无增量文本，仅补全结构化字段（前端卡片据此点亮观点/置信度徽章）
        yield StreamEvent(
            type="expert_opinion", expert_id=expert.id, round=round_index, content="", data=opinion.model_dump()
        )

    def _assemble_opinion(
        self,
        expert: ExpertRole,
        round_index: int,
        markdown: str,
        structured: dict,
        output_model: type,
        data_missing: bool,
    ) -> ExpertOpinion:
        """合并流式结果：末尾 JSON 块校验成结构化字段；缺失/非法时从已流文本提取保守字段。"""
        parsed = None
        if structured:
            try:
                parsed = output_model.model_validate(structured)
            except ValidationError:
                parsed = None
        if parsed is not None and parsed.stance.strip():
            conf = parsed.confidence
            delta = getattr(parsed, "confidence_delta", 0) or 0
            # 数据缺失时即便 LLM 违反规则，也强制压低置信度且禁止上调
            if data_missing:
                conf = min(conf, 30)
                delta = min(delta, 0)
            return ExpertOpinion(
                expert_id=expert.id,
                round=round_index,
                stance=parsed.stance,
                confidence=conf,
                key_evidence=parsed.key_evidence,
                reasoning=markdown[:4000],
                challenges=getattr(parsed, "challenges", []) or [],
                confidence_delta=delta,
                revised_stance=getattr(parsed, "revised_stance", "") or "",
            )
        # JSON 块缺失/非法 → 从已流文本正则提取保守字段（置信度 0 + 明确无法判断）
        fallback = self._parse_text_fallback(markdown, round_index)
        fallback.expert_id = expert.id
        fallback.reasoning = markdown[:4000] if markdown else fallback.reasoning
        if data_missing:
            fallback.confidence = min(fallback.confidence, 30)
        return fallback

    # ─── Round 2: 交叉辩论 ─────────────────────────────────────

    async def _call_expert_round2(
        self,
        expert: ExpertRole,
        question: str,
        shared_text: str,
        round1_opinions: list[ExpertOpinion],
    ) -> "AsyncGenerator[StreamEvent, None]":
        """单个专家的 Round 2 真流式调用：交叉辩论过程实时流出，末尾 JSON 块补全结构化字段"""
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

## 输出要求（严格遵循，两段式）
现在进入交叉辩论环节。请：
1. 审视其他专家的观点，找出逻辑漏洞或被忽略的风险；
2. 反思自己的判断是否需要修正；
3. 先用 Markdown 输出你的辩论与反思过程（对他方观点的审视、自我反思、修正/坚持的依据），这部分会实时流式展示给用户；
4. 然后另起一行，以 ```json 开头输出一个 JSON 代码块，仅包含以下字段：
{{
  "stance": "修正后的核心观点 (<=200字)",
  "confidence": 0-100的整数,
  "key_evidence": ["依据1", "依据2", ...],
  "challenges": ["对专家X的质疑: ...", ...],
  "confidence_delta": 置信度变化整数(如+5或-10),
  "revised_stance": "如果修正了观点，写修正后的观点；如果坚持，重复stance"
}}
{confidence_rule}"""

        async for ev in self._stream_expert_opinion(
            expert,
            round_index=2,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            output_model=_Round2Output,
            temperature=0.4,
            data_missing=data_missing,
        ):
            yield ev

    # ─── Round 3: 首席收敛 ─────────────────────────────────────

    async def _run_synthesis_stream(
        self,
        session: DebateSession,
        question: str,
        round1_opinions: list[ExpertOpinion],
        round2_opinions: list[ExpertOpinion],
    ) -> "AsyncGenerator[StreamEvent, None]":
        """首席分析师真流式收敛：完整报告随 token 流实时推给前端，末尾 JSON 块补全结构化字段。

        首席收敛必须降级，绝不能抛异常中断整个辩论 SSE 流。
        """
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

## 输出要求（严格遵循，两段式）
作为首席分析师，请综合所有专家的研判和辩论，输出最终收敛报告：
1. 先用 Markdown 输出完整收敛报告（共识与分歧梳理、各方论据权衡、概率评估与理由、最终建议、风险提示），这部分会实时流式展示给用户；
2. 然后另起一行，以 ```json 开头输出一个 JSON 代码块，仅包含以下字段：
{{
  "consensus_areas": ["共识点1", "共识点2", ...],
  "divergence_areas": ["分歧点1", "分歧点2", ...],
  "strongest_bull_case": "最强看多/正面论据",
  "strongest_bear_case": "最强看空/负面论据",
  "probability_assessment": 0-100的看涨/正面概率整数,
  "final_recommendation": "最终建议 (<=300字)",
  "risk_warnings": ["风险提示1", "风险提示2", ...],
  "minority_opinion": "少数派意见保留 (如有)"
}}
{probability_rule}"""

        chief_system = (
            "你是一位资深首席分析师，负责综合多位专家的研判结果，"
            "识别共识与分歧，权衡各方论据强度，给出最终概率评估和投资建议。"
            "你的判断应当客观、全面，既尊重多数派共识，也保留有价值的少数派意见。"
        )

        splitter = _StreamSplitter()
        deadline = time.monotonic() + _CHIEF_TIMEOUT
        report: Optional[ChiefReport] = None
        pending = ""
        last_emit = 0.0
        try:
            async for chunk in llm_service.generate_stream(
                user_prompt, chief_system, tier=ModelTier.FLAGSHIP, temperature=0.2
            ):
                if time.monotonic() > deadline:
                    raise asyncio.TimeoutError()
                prose = splitter.feed(chunk)
                if prose:
                    pending += prose
                # 打字机限速：同专家流，按固定节奏推送避免瞬间刷满
                now = time.monotonic()
                if pending and (_STREAM_EMIT_INTERVAL <= 0 or now - last_emit >= _STREAM_EMIT_INTERVAL):
                    emit, pending = pending[:_STREAM_CHARS_PER_TICK], pending[_STREAM_CHARS_PER_TICK:]
                    last_emit = now
                    yield StreamEvent(type="chief_report", message="首席分析师报告生成中...", content=emit)
            while pending:
                if time.monotonic() > deadline:
                    break
                await asyncio.sleep(_STREAM_EMIT_INTERVAL)
                emit, pending = pending[:_STREAM_CHARS_PER_TICK], pending[_STREAM_CHARS_PER_TICK:]
                yield StreamEvent(type="chief_report", message="首席分析师报告生成中...", content=emit)
            markdown, structured = splitter.finish()
            report = self._assemble_chief_report(markdown, structured, data_missing)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ [Orchestrator] 首席收敛流式失败，降级: {e}")
            # 中途失败保留已流出文本作为报告主体，仍不中断流程、不外泄报错
            markdown, structured = splitter.finish()
            report = self._assemble_chief_report(markdown, structured, data_missing) if markdown.strip() else None
            if report is None:
                report = ChiefReport(
                    probability_assessment=50,
                    final_recommendation="首席收敛报告生成异常，无法给出明确结论，建议稍后重试。",
                    full_report="> ⚠️ 首席收敛报告生成异常，本轮无法完成最终研判。请稍后重试。",
                    risk_warnings=["模型输出异常，未能生成完整收敛报告"],
                )
        session.chief_report = report
        # 结构化完成帧：无增量文本，仅补全结构化字段（前端据此渲染概率/共识/分歧卡片）
        yield StreamEvent(type="chief_report", content="", data=report.model_dump())

    def _assemble_chief_report(self, markdown: str, structured: dict, data_missing: bool) -> ChiefReport:
        """合并首席流式结果：末尾 JSON 块校验成结构化字段，流式 Markdown 作为 full_report。"""
        report: Optional[ChiefReport] = None
        if structured:
            structured.pop("full_report", None)
            try:
                report = ChiefReport.model_validate(structured)
            except ValidationError:
                report = None
        if report is None:
            # JSON 块缺失/非法：尽力从文本提取概率，整段作为报告主体
            import re as _re

            m_prob = _re.search(r"(\d{1,3})\s*%", markdown)
            prob = int(m_prob.group(1)) if m_prob else 50
            prob = min(max(prob, 0), 100)
            report = ChiefReport(probability_assessment=prob, final_recommendation=markdown[:300])
        report.full_report = markdown or report.full_report
        # 数据缺失时兜底：概率收敛到 40-60 不确定区间，避免伪精确
        if data_missing and report.probability_assessment is not None:
            report.probability_assessment = min(max(report.probability_assessment, 40), 60)
        return report


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
