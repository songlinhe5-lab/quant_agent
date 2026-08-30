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

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CompactConfig:
    """
    AGENT-16 · 摘要压缩配置（支持环境变量）

    关键参数：
    - SUMMARY_SYSTEM_PROMPT: Pro 模型系统提示词（默认专业化量化交易场景）
    - COMPACT_SYSTEM_PROMPT: 压缩器核心提示词（提取关键信息）
    - MAX_SUMMARY_TOKENS: 最大摘要长度（默认 2000 tokens）
    """

    # System Prompts (可配置)
    summary_system_prompt: str = (
        "你是一个专业的量化交易记忆压缩助手。请高度凝练地总结以下对话中的关键事实、决策依据和结论，"
        "用简洁专业的中文输出（不超过 2000 字）。"
    )
    compact_system_prompt: str = "以下是需要压缩的历史对话片段，请提取核心事实与决策。"

    # Token Limits (可配置)
    max_summary_tokens: int = 2000

    @classmethod
    def from_env(cls) -> "CompactConfig":
        """从环境变量加载配置"""
        return cls(
            summary_system_prompt=os.getenv(
                "HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT",
                "你是一个专业的量化交易记忆压缩助手。请高度凝练地总结以下对话中的关键事实、决策依据和结论，用简洁专业的中文输出（不超过 2000 字）。",
            ),
            compact_system_prompt=os.getenv(
                "HERMES_COMPACT_SYSTEM_PROMPT", "以下是需要压缩的历史对话片段，请提取核心事实与决策。"
            ),
            max_summary_tokens=int(os.getenv("HERMES_COMPACT_MAX_SUMMARY_TOKENS", "2000")),
        )


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
        min_items_retained: int = 10,
        config: Optional[CompactConfig] = None,
    ):
        self.client = llm_client
        self.event_log = event_log
        self.model = model
        self.pro_model = pro_model
        self.max_tokens_before_compress = max_tokens_before_compress
        self.min_items_retained = min_items_retained
        # 配置：优先使用传入配置，否则从环境变量加载
        self.config = config or CompactConfig.from_env()

    async def maybe_compress(
        self,
        messages: List[Dict[str, Any]],
        estimate_tokens_func,
        max_messages: int = 30,
        max_tool_len: int = 800,
    ) -> bool:
        """
        检查是否需要压缩，若需要则执行摘要压缩。

        流程：
        1. 检查 token 是否超阈值
        2. 尝试 LLM 摘要压缩
        3. 摘要失败 → 抛异常，由调用方决定 fallback（滑动窗口等）

        Returns:
            True 已压缩，False 未触发
        """
        current_tokens = estimate_tokens_func()

        # 未达阈值，跳过
        if current_tokens <= self.max_tokens_before_compress:
            return False

        print(f"🗜️ [Agent-16] 上下文达 {current_tokens} tokens，触发摘要压缩...")

        return await self._compress_with_summary(messages, max_messages, max_tool_len)

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
        # 保护 tool 配对：保留窗口起点不能落在 tool 消息上。
        # 若切点落在 tool 消息（其配对的 assistant(tool_calls) 已被裁进摘要区），
        # 压缩后序列会以孤立 tool 开头，下一轮 LLM 调用报 400
        # "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"。
        # 向后推进 cut_idx，把无配对的 tool 结果一并裁掉（孤立 tool 无保留价值）。
        while cut_idx < len(messages) and messages[cut_idx].get("role") == "tool":
            cut_idx += 1

        items_to_compact = messages[1:cut_idx]  # 排除 system
        original_token_count = sum(len(str(item)) for item in items_to_compact)

        # 2. 构建压缩 Prompt（使用配置的模板）
        prompt = self._build_compaction_prompt(items_to_compact)

        # 3. 调用 Pro 模型生成摘要
        try:
            response = await self.client.chat.completions.create(
                model=self.pro_model,
                messages=[
                    {
                        "role": "system",
                        "content": self.config.summary_system_prompt,  # 使用配置的系统提示词
                    },
                    *prompt,
                ],
                temperature=0.3,
                max_tokens=self.config.max_summary_tokens,  # 使用配置的最大长度
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

    async def _fallback_record(self, messages: List[Dict[str, Any]], max_messages: int) -> None:
        """Fallback 降级：仅记录审计事件，滑动窗口由调用方 _compress_memory 统一处理"""
        if self.event_log:
            self.event_log.record_memory_op(
                "compact",
                f"method=fallback_truncate msg_count={len(messages)} max_messages={max_messages}",
            )
        print(f"⚠️ [Agent-16] 摘要降级为滑动窗口截断（{len(messages)} 条消息）")

    def _build_compaction_prompt(self, items_to_compact: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """构建压缩 Prompt（使用配置的模板）"""
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
            {"role": "system", "content": self.config.compact_system_prompt}  # 使用配置的提示词
        ] + simplified_items
