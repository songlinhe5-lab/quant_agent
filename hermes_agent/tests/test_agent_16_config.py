"""
AGENT-16 · Prompt 模板参数化测试

验证 CompactConfig 的配置化机制。
"""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from hermes_agent.compact import CompactConfig, ContextCompressor


def test_compact_config_default_values():
    """测试默认配置值"""
    config = CompactConfig()

    assert "量化交易记忆压缩助手" in config.summary_system_prompt
    assert "提取核心事实" in config.compact_system_prompt
    assert config.max_summary_tokens == 2000


def test_compact_config_from_env_override():
    """测试环境变量覆盖"""
    # 设置环境变量
    os.environ["HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT"] = "自定义系统提示词 A"
    os.environ["HERMES_COMPACT_SYSTEM_PROMPT"] = "自定义系统提示词 B"
    os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"] = "3000"

    try:
        config = CompactConfig.from_env()

        assert config.summary_system_prompt == "自定义系统提示词 A"
        assert config.compact_system_prompt == "自定义系统提示词 B"
        assert config.max_summary_tokens == 3000
    finally:
        # 清理环境变量
        del os.environ["HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT"]
        del os.environ["HERMES_COMPACT_SYSTEM_PROMPT"]
        del os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"]


def test_compact_config_partial_env_override():
    """测试部分环境变量覆盖（使用混合模式）"""
    os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"] = "2500"

    try:
        config = CompactConfig.from_env()

        # 只覆盖了一个，其他两个应该使用默认值
        assert "量化交易记忆压缩助手" in config.summary_system_prompt
        assert "提取核心事实" in config.compact_system_prompt
        assert config.max_summary_tokens == 2500
    finally:
        del os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"]


@pytest.mark.asyncio
async def test_context_compressor_uses_custom_config():
    """测试 ContextCompressor 使用自定义配置"""
    client = AsyncMock()
    event_log = MagicMock()

    # 自定义配置
    custom_config = CompactConfig(
        summary_system_prompt="专业版压缩助手",
        compact_system_prompt="提取关键决策",
        max_summary_tokens=4000,
    )

    compressor = ContextCompressor(
        llm_client=client,
        event_log=event_log,
        config=custom_config,  # 注入自定义配置
    )

    # 验证配置被正确注入
    assert compressor.config.summary_system_prompt == "专业版压缩助手"
    assert compressor.config.compact_system_prompt == "提取关键决策"
    assert compressor.config.max_summary_tokens == 4000


@pytest.mark.asyncio
async def test_context_compressor_fallback_to_env_config():
    """测试 ContextCompressor 环境变量降级"""
    client = AsyncMock()
    event_log = MagicMock()

    # 设置环境变量
    os.environ["HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT"] = "来自环境的系统提示"
    os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"] = "3500"

    try:
        # 不传 config 参数，应自动从环境变量加载
        compressor = ContextCompressor(llm_client=client, event_log=event_log)

        assert compressor.config.summary_system_prompt == "来自环境的系统提示"
        assert compressor.config.max_summary_tokens == 3500
    finally:
        del os.environ["HERMES_COMPACT_SUMMARY_SYSTEM_PROMPT"]
        del os.environ["HERMES_COMPACT_MAX_SUMMARY_TOKENS"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
