"""
选民看板 (COMM-02) 单测
========================

- FMP_API_KEY 幽灵配置已从 Settings 移除（零幻觉：不伪造未使用数据源）
- Tavily / Bocha / Jina 经 ensure_search_sources_registered 进入 registry，
  自动归入「已接入」分类并带中文标签（与 fred/dbnomics/rbi 同处理）
"""

import asyncio
from types import SimpleNamespace

from backend.core.config import Settings
from backend.routers.datasource_vote import get_vote_board
from backend.services.datasource.source_registry import datasource_registry


def test_fmp_api_key_removed_from_settings():
    # FMP_API_KEY 是未消费的幽灵配置，必须从 Settings 删除
    assert "fmp_api_key" not in Settings.model_fields
    assert "FMP_API_KEY" not in Settings.model_fields


class TestVoteBoardSearchSources:
    def setup_method(self):
        datasource_registry.clear()

    def teardown_method(self):
        datasource_registry.clear()

    def test_search_sources_in_connected_with_labels(self):
        fake_user = SimpleNamespace(username="test")
        board = asyncio.run(get_vote_board(current_user=fake_user))
        connected = {e["name"]: e for e in board["connected"]}
        # 三搜索源应出现在「已接入」且带中文标签
        assert {"tavily", "bocha", "jina"} <= set(connected)
        assert connected["tavily"]["label"] == "Tavily 搜索"
        assert connected["bocha"]["label"] == "博查 Bocha"
        assert connected["jina"]["label"] == "Jina Reader"
        # 宏观源标签仍保留（回归）
        assert connected["fred"]["label"] == "FRED 宏观经济"

    def test_search_sources_votable(self):
        # 路由层 (get_vote_board/cast_vote) 会先 ensure 注册，这里模拟该触发
        from backend.services.datasource.adapters.search import ensure_search_sources_registered

        ensure_search_sources_registered()
        from backend.routers.datasource_vote import _all_votable

        names = _all_votable()
        assert {"tavily", "bocha", "jina"} <= names
