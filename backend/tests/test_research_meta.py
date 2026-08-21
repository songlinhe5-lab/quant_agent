"""
COPILOT-12: GET /research/meta 注册表元数据端点测试

覆盖：tools_count 来自 lifecycle.global_registry.tools 数量（实时读取，非导入时快照），
model_name 来自 settings.llm_model（LLM_MODEL 默认 deepseek-v4-flash）。
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.routers.research import get_research_meta


@pytest.mark.asyncio
async def test_meta_registry_none_returns_zero():
    """global_registry 为 None 时 tools_count 降级为 0，model_name 有默认值"""
    with patch("backend.routers.research.lifecycle.global_registry", None):
        result = await get_research_meta()
    assert result["tools_count"] == 0
    assert result["model_name"]  # 非空


@pytest.mark.asyncio
async def test_meta_registry_with_tools_counts():
    """global_registry 挂载 5 个工具时 tools_count=5"""
    reg = MagicMock()
    reg.tools = {f"tool_{i}": object() for i in range(5)}
    with patch("backend.routers.research.lifecycle.global_registry", reg):
        result = await get_research_meta()
    assert result["tools_count"] == 5
