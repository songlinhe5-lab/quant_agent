"""
AGENT-16 · 摘要压缩取代破坏性截断

对标 openai/codex `compact.rs` / `compact_model_fallback.rs` + hermes prompt_caching。

核心改进：
1. 被裁部分用 Pro 模型生成摘要，产出 ContextCompactionItem 写回 messages 头部
2. 摘要失败时 fallback 现有有损截断
3. Token-based 截断策略统一（事件日志 4KB / tool 内容 800 字）
4. 压缩本身可审计（event_log → memory/compact）

数据结构：
    ContextCompactionItem = {
        "role": "assistant",
        "content": None,
        "tool_calls": [...]  # 可选，引用原工具调用
    }

    CompactMetadata = {
        "original_range": {"start": int, "end": int},
        "token_before": int,
        "token_after": int,
        "compaction_method": "llm_summary" | "fallback_truncate",
        "timestamp": float
    }
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class CompactMetadata:
    """压缩元数据（不进入 LLM 上下文，仅审计）"""

    original_range_start: int
    original_range_end: int
    token_before: int
    token_after: int
    compaction_method: str  # "llm_summary" | "fallback_truncate"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_range": {"start": self.original_range_start, "end": self.original_range_end},
            "token_before": self.token_before,
            "token_after": self.token_after,
            "compaction_method": self.compaction_method,
            "timestamp": self.timestamp,
        }


@dataclass
class ContextCompactionItem:
    """压缩后的摘要项（进入 LLM 上下文）"""

    summary: str  # 摘要文本
    metadata: CompactMetadata
    original_items_count: int  # 被压缩的消息数量

    def to_message(self) -> Dict[str, Any]:
        """转换为 LLM 可见的 message 格式"""
        return {
            "role": "assistant",
            "content": f"[COMPACTED {self.original_items_count} items]\n\n{self.summary}",
        }


class ContextCompressor:
    """上下文压缩器 —— 摘要取代截断（AGENT-16）"""

    def __init__(
        self,
        llm_client: Any,
        event_log: Any,
        model: str = "deepseek-chat",
        pro_model: str = "deepseek-pro",
        max_tokens_before_compress: int = 120000,
        max_summary_tokens: int = 5000,
        min_items_retained: int = 10,
    ):
        self.client = llm_client
        self.event_log = event_log
        self.model = model
        self.pro_model = pro_model
        self.max_tokens_before_compress = max_tokens_before_compress
        self.max_summary_tokens = max_summary_tokens
        self.min_items_retained = min_items_retained

    async def maybe_compress(
        self,
        messages: List[Dict[str, Any]],
        estimate_tokens_func,
        max_messages: int = 30,
        max_tool_len: int = 800,
    ) -> bool:
        """
        检查是否需要压缩，若需要则执行摘要压缩或 fallback 截断。

        Returns:
            True 已压缩（摘要或 fallback），False 未触发
        """
        current_tokens = estimate_tokens_func()

        # 未达阈值，跳过
        if current_tokens <= self.max_tokens_before_compress:
            return False

        print(f"🗜️ [Agent-16] 上下文达 {current_tokens} tokens，触发摘要压缩...")

        try:
            return await self._compress_with_summary(messages, max_messages, max_tool_len)
        except Exception as e:
            print(f"⚠️ [Agent-16] 摘要压缩失败：{e}，降级为 fallback 截断")
            return await self._fallback_truncate(messages, max_messages, max_tool_len)

    async def _compress_with_summary(
        self, messages: List[Dict[str, Any]], max_messages: int, max_tool_len: int
    ) -> bool:
        """执行摘要压缩路径"""
        if len(messages) <= self.min_items_retained * 2:
            print("ℹ️ [Agent-16] 当前消息数已低于最小保留线，跳过压缩")
            return False

        # 1. 确定要压缩的范围（除 system + 最新 min_items_retained 条）
        cut_idx = len(messages) - self.min_items_retained
        if cut_idx <= 1:
            print("ℹ️ [Agent-16] 无足够历史消息可压缩")
            return False

        items_to_compact = messages[1:cut_idx]  # 排除 system
        original_token_count = sum(len(str(item)) for item in items_to_compact)

        # 2. 构建压缩 Prompt（参考 codex compact.rs）
        prompt = self._build_compaction_prompt(items_to_compact)

        # 3. 调用 Pro 模型生成摘要
        try:
            response = await self.client.chat.completions.create(
                model=self.pro_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的量化交易记忆压缩助手。请高度凝练地总结以下对话中的关键事实、决策依据和结论，用简洁专业的中文输出（不超过 2000 字）。",
                    },
                    *prompt,
                ],
                temperature=0.3,
                max_tokens=self.max_summary_tokens,
            )

            summary = response.choices[0].message.content.strip()
            if not summary:
                raise RuntimeError("模型返回空摘要")

            # 4. 构造 CompactMetadata（审计用）
            metadata = CompactMetadata(
                original_range_start=1,
                original_range_end=cut_idx,
                token_before=original_token_count,
                token_after=len(summary),
                compaction_method="llm_summary",
            )

            # 5. 构造 ContextCompactionItem
            compaction_item = ContextCompactionItem(
                summary=summary, metadata=metadata, original_items_count=len(items_to_compact)
            )

            # 6. 替换旧消息为摘要项（直接在原列表操作）
            messages[1:cut_idx] = [compaction_item.to_message()]

            # 7. 审计记录
            if self.event_log:
                self.event_log.record_memory_op(
                    "compact",
                    f"method={metadata.compaction_method} range=[{metadata.original_range_start}:{metadata.original_range_end}] tokens={metadata.token_before}->{metadata.token_after}",
                )

            print(
                f"✅ [Agent-16] 摘要压缩完成：{len(items_to_compact)} 条消息 → 1 条摘要 ({metadata.token_before}→{metadata.token_after} tokens)"
            )
            return True

        except Exception as e:
            raise RuntimeError(f"Pro 模型摘要失败：{e}")

    async def _fallback_truncate(self, messages: List[Dict[str, Any]], max_messages: int, max_tool_len: int) -> bool:
        """Fallback 降级：现有有损截断逻辑"""
        from backend.utils.text_utils import safe_truncate

        # 1. 截断巨型 Tool 返回值
        for i in range(1, len(messages) - 4):
            msg = messages[i]
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
                if len(msg["content"]) > max_tool_len:
                    msg["content"] = safe_truncate(
                        msg["content"],
                        max_tool_len,
                        suffix=f"\n... [老旧数据被折叠，省略 {len(msg['content']) - max_tool_len} 字符以释放内存] ...",
                    )

        # 2. 滑动窗口截断
        if len(messages) > max_messages:
            system_msg = [messages[0]]
            cut_idx = len(messages) - max_messages
            while cut_idx < len(messages) and messages[cut_idx].get("role") in ["tool", "assistant"]:
                cut_idx += 1

            truncated_items = messages[cut_idx : -self.min_items_retained]
            truncated_count = len(truncated_items)
            truncated_tokens = sum(len(str(item)) for item in truncated_items)

            messages[:] = system_msg + messages[cut_idx:]

            # 3. 审计记录
            if self.event_log:
                metadata = CompactMetadata(
                    original_range_start=1,
                    original_range_end=cut_idx,
                    token_before=truncated_tokens,
                    token_after=sum(len(str(m)) for m in messages),
                    compaction_method="fallback_truncate",
                )
                self.event_log.record_memory_op(
                    "compact",
                    f"method={metadata.compaction_method} range=[{metadata.original_range_start}:{metadata.original_range_end}] items={truncated_count}",
                )

            print(f"✅ [Agent-16] Fallback 截断完成：{truncated_count} 条消息被丢弃 ({truncated_tokens} tokens)")
            return True

        return False

    def _build_compaction_prompt(self, items_to_compact: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """构建压缩 Prompt（提取关键信息，避免过长）"""
        # 只提取 user 和 assistant 消息，tool 消息简化
        simplified_items = []
        for item in items_to_compact:
            role = item.get("role", "")
            content = item.get("content", "")

            if role == "tool":
                # Tool 消息只保留名称和状态，丢弃详细内容
                name = item.get("name", "unknown")
                status = "ok" if isinstance(content, str) and "error" not in content.lower() else "error"
                simplified_items.append({"role": "tool", "content": f"[Tool {name} executed, status={status}]"})
            else:
                simplified_items.append(item)

        return [
            {"role": "system", "content": "以下是需要压缩的历史对话片段，请提取核心事实与决策。"}
        ] + simplified_items
