"""
COPILOT-11: HermesAgent 记忆管理 Mixin
从 agent.py 拆出的会话持久化 / 记忆自愈 / 压缩 / 知识库沉淀 / TokenGuard 逻辑。
通过 Mixin 继承挂载到 HermesAgent 类，共享 self.messages / self.redis_client 等状态。
"""

import asyncio
import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List

from rich.console import Console

# ── 常量 ────────────────────────────────────────────────────────────
_AUTO_SINK_KB = os.getenv("AUTO_SINK_KB", "true").lower() in ("1", "true", "yes", "on")

# 事实抽取正则：数字 + 单位/货币/百分比
_FACT_RE = re.compile(
    r"[^\n]*?\d[\d,.]*\s*(?:亿|万|百万|千亿|%|percent|美元|人民币|元|港元|股|手|吨|桶|磅|盎司|bps|bp)[^\n]*"
)


class MemoryOperationsMixin:
    """记忆管理 Mixin——需由宿主类提供 self.messages / self.redis_client / self.console / self.session_id 等"""

    console: Console
    messages: List[Dict[str, Any]]
    redis_client: Any
    session_id: str

    # ── Token 估算 ──────────────────────────────────────────────────
    def _estimate_tokens(self) -> int:
        """粗略估算当前上下文 token 数（中文约 1 字/token，英文约 4 字符/token，取保守上界）"""
        try:
            raw = json.dumps(self.messages, ensure_ascii=False, default=str)
        except Exception:
            raw = str(self.messages)
        return int(len(raw) / 1.6)

    # ── 记忆压缩 ────────────────────────────────────────────────────
    def _compress_memory(self, max_messages: int = 30, max_tool_len: int = 800, hard_cap_tokens: int = 60000):
        """上下文记忆智能压缩机制：防止历史记录过长导致 Token 溢出与性能下降"""
        if len(self.messages) <= 2:
            return

        aggressive = self._estimate_tokens() > hard_cap_tokens
        eff_tool_len = 2000 if aggressive else max_tool_len
        eff_max_messages = 20 if aggressive else max_messages

        # 1. 有损压缩：截断非最新轮次的巨型 Tool 返回值
        from backend.utils.text_utils import safe_truncate

        for i in range(1, len(self.messages) - 4):
            msg = self.messages[i]
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                if len(msg["content"]) > eff_tool_len:
                    msg["content"] = safe_truncate(
                        msg["content"],
                        eff_tool_len,
                        suffix="\n... [老旧数据被折叠，省略 {omitted} 字符以释放内存] ...",
                    )

        # 2. 滑动窗口
        if len(self.messages) > eff_max_messages:
            self.console.print(
                f"[dim yellow]🗜️ [Memory] 上下文达 {len(self.messages)} 条，触发滑动窗口自动瘦身...[/dim yellow]"
            )
            system_msg = [self.messages[0]]
            cut_idx = len(self.messages) - eff_max_messages
            while cut_idx < len(self.messages) and self.messages[cut_idx].get("role") in ["tool", "assistant"]:
                cut_idx += 1
            self.messages = system_msg + self.messages[cut_idx:]
            # AGENT-01: 压缩只影响运行时窗口，事件日志不被删改，仅记录事件
            _evlog = getattr(self, "event_log", None)
            if _evlog is not None:
                _evlog.record_memory_op("compress", f"window_cut={cut_idx} aggressive={aggressive}")

    # ── 记忆自愈 ────────────────────────────────────────────────────
    def _heal_memory(self):
        """修复因为异常中断导致的孤立 tool_calls 破坏上下文记录的问题"""
        healed = []
        for m in self.messages:
            if healed and healed[-1].get("role") == "assistant" and healed[-1].get("tool_calls"):
                if m.get("role") != "tool":
                    healed.pop()
            healed.append(m)

        if healed and healed[-1].get("role") == "assistant" and healed[-1].get("tool_calls"):
            self.console.print("[dim red]🐛 [Memory] 检测到末尾残留未闭环的 tool_calls，已剔除。[/dim red]")
            healed.pop()

        final_healed = []
        i = 0
        while i < len(healed):
            msg = healed[i]
            final_healed.append(msg)
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                tool_call_ids = {tc["id"] for tc in msg["tool_calls"]}
                received_tool_ids = set()
                j = i + 1
                while j < len(healed) and healed[j].get("role") == "tool":
                    received_tool_ids.add(healed[j].get("tool_call_id"))
                    j += 1
                missing_ids = tool_call_ids - received_tool_ids
                for missing_id in missing_ids:
                    tool_name = "unknown"
                    for tc in msg["tool_calls"]:
                        if tc["id"] == missing_id:
                            tool_name = tc.get("function", {}).get("name", "unknown")
                            break
                    self.console.print(
                        f"[dim yellow]🩹 [Memory] 补充缺失的 tool 响应: {tool_name} ({missing_id[:8]}...)[/dim yellow]"
                    )
                    final_healed.append(
                        {
                            "role": "tool",
                            "tool_call_id": missing_id,
                            "name": tool_name,
                            "content": '{"status": "error", "message": "工具执行中断，未获取到结果"}',
                        }
                    )
            i += 1

        if len(final_healed) != len(self.messages):
            self.console.print(
                "\n[dim yellow]🩹 [Memory] 检测到破损的工具调用上下文，已自动完成记忆修复！[/dim yellow]"
            )
            _heal_delta = len(final_healed) - len(self.messages)
            self.messages = final_healed
            # AGENT-01: 自愈事件入日志（修复行为本身可审计）
            _evlog = getattr(self, "event_log", None)
            if _evlog is not None:
                _evlog.record_memory_op("heal", f"delta={_heal_delta}")

        self._compress_memory()

    # ── 会话持久化 (Redis 热 + PG 冷) ──────────────────────────────
    async def _save_session(self):
        """将会话历史保存到 Redis (热数据)，并抛出后台任务异步落库 PostgreSQL (冷数据)"""
        try:
            await self.redis_client.set(self.memory_key, json.dumps(self.messages, ensure_ascii=False), ex=43200)
            asyncio.create_task(self._async_db_upsert(self.session_id, list(self.messages)))
        except Exception as e:
            print(f"⚠️ [Memory] 记忆保存失败: {e}")

    async def _load_session(self):
        """从 Redis 加载历史记录。若未命中，尝试从 PostgreSQL 唤醒冷数据"""
        try:
            raw_data = await self.redis_client.get(self.memory_key)
            if raw_data:
                saved_messages = json.loads(raw_data)
                self._apply_system_prompt(saved_messages)
                self.messages = saved_messages
                print(f"📦 [Memory] 成功从 Redis 加载历史对话，共恢复 {len(self.messages) - 1} 条记录。")
                return
        except Exception as e:
            print(f"⚠️ [Memory] 从 Redis 读取历史失败: {e}")

        try:

            def fetch_db():
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == self.session_id).first()
                    if record and record.messages:
                        return record.messages
                return None

            db_messages = await asyncio.to_thread(fetch_db)
            if db_messages:
                self._apply_system_prompt(db_messages)
                self.messages = db_messages
                print(f"🗄️ [Memory] 成功从 PostgreSQL 唤醒冷数据对话，共恢复 {len(self.messages) - 1} 条记录。")
                await self._save_session()
                return
        except Exception as e:
            print(f"⚠️ [Memory] 从 PostgreSQL 唤醒冷数据失败: {e}")

        self.messages = [{"role": "system", "content": self.system_prompt}]

    async def _async_db_upsert(self, session_id: str, messages: list):
        """后台守护任务：将历史记忆异步 Upsert 到 PostgreSQL"""
        try:

            def check_needs_title():
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
                    return record is None or record.title == "新对话"

            needs_title = await asyncio.to_thread(check_needs_title)
            new_title = "新对话"
            if needs_title:
                user_content = ""
                for m in messages:
                    if m.get("role") == "user":
                        c = m.get("content")
                        if isinstance(c, str):
                            user_content = c.strip()
                        elif isinstance(c, list):
                            user_content = next(
                                (item.get("text", "") for item in c if item.get("type") == "text"), ""
                            ).strip()
                        if user_content:
                            break
                if user_content:
                    try:
                        response = await self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {
                                    "role": "system",
                                    "content": "你是一个标题生成器。请用极简、专业的中文（不超过3个词或10个汉字）精准总结用户的提问作为标题。严禁输出任何标点符号、引号或其他解释性文字。",
                                },
                                {"role": "user", "content": user_content},
                            ],
                            temperature=0.3,
                            max_tokens=15,
                        )
                        _t_usage = getattr(response, "usage", None)
                        if _t_usage is not None:
                            from hermes_agent.agent import token_usage_store

                            await token_usage_store.record(
                                prompt_tokens=getattr(_t_usage, "prompt_tokens", 0),
                                completion_tokens=getattr(_t_usage, "completion_tokens", 0),
                                total_tokens=getattr(_t_usage, "total_tokens", 0),
                            )
                        raw_title = response.choices[0].message.content
                        new_title = raw_title.strip("。，. \"'") if raw_title else user_content[:20]
                        from hermes_agent.agent import SessionTitleValidator, ValidationError

                        validated = SessionTitleValidator(title=new_title)
                        new_title = validated.title
                        print(f"🧠 [Agent Memory] 智能标题已生成: {new_title}")
                    except ValidationError as ve:
                        print(f"⚠️ [Agent Memory] 标题校验未通过 ({ve.errors()[0]['msg']})，降级为文本截断")
                        new_title = user_content[:20] + ("..." if len(user_content) > 20 else "")
                    except Exception as e:
                        print(f"⚠️ [Agent Memory] 智能标题生成失败，降级为文本截断: {e}")
                        new_title = user_content[:20] + ("..." if len(user_content) > 20 else "")

            def db_op():
                from backend.core.database import SessionLocal
                from backend.core.models import AgentSession

                with SessionLocal() as db:
                    record = db.query(AgentSession).filter(AgentSession.session_id == session_id).first()
                    if record:
                        record.messages = messages
                        if needs_title and new_title != "新对话":
                            record.title = new_title
                    else:
                        new_record = AgentSession(session_id=session_id, title=new_title, messages=messages)
                        db.add(new_record)
                    db.commit()

            await asyncio.to_thread(db_op)
        except Exception as e:
            print(f"⚠️ [DB Error] 异步落库 PostgreSQL 失败: {e}")

    # ── TokenGuard 防爆护栏 ─────────────────────────────────────────
    async def _guard_before_llm(self, window_sec: int = 3600, max_calls: int = 60, max_input_tokens: int = 120000):
        """每次向 LLM 发送请求前的防爆护栏"""
        try:
            rl_key = f"hermes:ratelimit:{self.session_id}"
            calls = await self.redis_client.incr(rl_key)
            if calls == 1:
                await self.redis_client.expire(rl_key, window_sec)
            if calls > max_calls:
                raise RuntimeError(
                    f"🚨 [TokenGuard] 会话 {self.session_id} 在 {window_sec}s 内已调用 LLM {calls} 次"
                    f"（上限 {max_calls}），疑似死循环或前端重连狂发，已强制熔断。"
                )
        except RuntimeError:
            raise
        except Exception as e:
            print(f"⚠️ [TokenGuard] 限流计数失败，降级放行: {e}")

        est = self._estimate_tokens()
        if est > max_input_tokens:
            self.console.print(
                f"[red]🚨 [TokenGuard] 单次上下文估算 {est} token 超预算 {max_input_tokens}，强制激进压缩...[/red]"
            )
            self._compress_memory(hard_cap_tokens=1)
            est = self._estimate_tokens()
            if est > max_input_tokens:
                raise RuntimeError(
                    f"🚨 [TokenGuard] 激进压缩后仍超预算（{est} > {max_input_tokens} token），阻断本次请求。"
                )

    # ── 对话事实沉淀到知识库 (PR-B) ────────────────────────────────
    async def _sink_to_kb(self, final_content: str) -> int:
        """将本轮结论中的事实抽取后写入知识库，返回写入片段数"""
        if not _AUTO_SINK_KB or not final_content:
            return 0

        facts = _FACT_RE.findall(final_content)
        if not facts:
            return 0

        cleaned: list[str] = []
        seen: set[str] = set()
        for f in facts:
            text = f.strip()
            if len(text) < 8 or len(text) > 500:
                continue
            if text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if not cleaned:
            return 0

        try:
            from backend.core.config import settings
            from backend.core.embeddings import get_embeddings

            vectors = get_embeddings(cleaned)
            if not vectors or len(vectors) != len(cleaned):
                self.console.print("⚠️ [SinkKB] Embedding 服务不可用，放弃本轮沉淀。")
                return 0
        except Exception as e:
            self.console.print(f"⚠️ [SinkKB] Embedding 失败: {e}")
            return 0

        try:
            from backend.core.database import SessionLocal
            from backend.core.models import WebpageKnowledgeBase

            emb_version = settings.embedding_model
            ts = int(time.time())
            source_url = f"chat://{self.session_id}"
            rows = []
            for fact, vec in zip(cleaned, vectors):
                fid = f"chat_sink_{self.session_id}_{hashlib.md5(fact.encode()).hexdigest()[:12]}"
                rows.append(
                    WebpageKnowledgeBase(
                        id=fid,
                        url=source_url,
                        content=fact,
                        timestamp=ts,
                        category="general",
                        embedding_model_version=emb_version,
                        embedding=vec,
                    )
                )
            with SessionLocal() as db:
                db.query(WebpageKnowledgeBase).filter(WebpageKnowledgeBase.id.in_([r.id for r in rows])).delete(
                    synchronize_session=False
                )
                db.bulk_save_objects(rows)
                db.commit()
            self.console.print(f"📥 [SinkKB] 本轮沉淀 {len(rows)} 条事实到知识库 (session={self.session_id})")
            return len(rows)
        except Exception as e:
            self.console.print(f"⚠️ [SinkKB] 入库失败: {e}")
            return 0
