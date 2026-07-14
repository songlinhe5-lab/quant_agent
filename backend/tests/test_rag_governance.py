"""
AI-04 · RAG 知识库治理单元测试

覆盖:
- 分类 TTL 映射正确性
- 检索质量监控: 连续低相似度告警
- 检索质量监控: 高相似度重置计数
- Embedding 版本检查 (mock DB)
- 质量统计信息
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCategoryTTL:
    """分类 TTL 映射"""

    def test_ttl_values(self):
        from backend.services.screener_service import ScreenerService

        ttl = ScreenerService.CATEGORY_TTL
        assert ttl["financial_report"] == 90 * 24 * 3600
        assert ttl["news"] == 7 * 24 * 3600
        assert ttl["macro"] == 30 * 24 * 3600
        assert ttl["general"] == 90 * 24 * 3600

    def test_ttl_has_all_categories(self):
        from backend.services.screener_service import ScreenerService

        expected = {"financial_report", "news", "macro", "general"}
        assert set(ScreenerService.CATEGORY_TTL.keys()) == expected


class TestRetrievalQualityMonitor:
    """检索质量监控"""

    def test_low_similarity_increments_streak(self):
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        # 连续低相似度
        for _ in range(5):
            result = svc.record_retrieval_similarity(0.3)
        assert not result  # 未到阈值不告警
        assert svc._low_similarity_streak == 5

    def test_alert_triggered_at_threshold(self):
        from backend.services.rag_governance import LOW_QUALITY_STREAK, RAGGovernanceService

        svc = RAGGovernanceService()
        result = False
        for _ in range(LOW_QUALITY_STREAK):
            result = svc.record_retrieval_similarity(0.3)
        assert result  # 达到阈值触发告警

    def test_high_similarity_resets_streak(self):
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        # 先积累一些低相似度
        for _ in range(5):
            svc.record_retrieval_similarity(0.3)
        assert svc._low_similarity_streak == 5
        # 一次高相似度重置
        svc.record_retrieval_similarity(0.8)
        assert svc._low_similarity_streak == 0

    def test_quality_stats(self):
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        svc.record_retrieval_similarity(0.3)
        svc.record_retrieval_similarity(0.8)
        stats = svc.get_quality_stats()
        assert stats["total_retrievals"] == 2
        assert stats["low_similarity_count"] == 1
        assert stats["current_streak"] == 0
        assert stats["threshold"] == 0.6

    def test_empty_stats(self):
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        stats = svc.get_quality_stats()
        assert stats["total_retrievals"] == 0
        assert stats["low_similarity_rate"] == 0.0


class TestEmbeddingVersionCheck:
    """Embedding 版本管理"""

    @pytest.mark.asyncio
    async def test_check_version_no_table(self):
        """表不存在时返回 None"""
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.scalar.return_value = False

        with patch("backend.core.database.engine") as mock_engine:
            mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
            result = await svc.check_embedding_version()
        # 表不存在应返回 None
        assert result is None

    @pytest.mark.asyncio
    async def test_trigger_rebuild_returns_result(self):
        """触发重建应返回状态字典"""
        from backend.services.rag_governance import RAGGovernanceService

        svc = RAGGovernanceService()
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_conn.execute.return_value = mock_result

        with patch("backend.core.database.engine") as mock_engine:
            mock_engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_engine.begin.return_value.__exit__ = MagicMock(return_value=False)
            with patch("backend.core.config.settings") as mock_settings:
                mock_settings.embedding_model = "test-model-v2"
                with patch("backend.core.redis_client.redis_client", new_callable=AsyncMock):
                    result = await svc.trigger_embedding_rebuild()

        assert result["status"] == "success"
        assert result["deleted_count"] == 5
        assert result["new_version"] == "test-model-v2"


class TestWebpageKnowledgeBaseModel:
    """模型字段检查"""

    def test_model_has_category_field(self):
        from backend.core.models import WebpageKnowledgeBase

        assert hasattr(WebpageKnowledgeBase, "category")

    def test_model_has_embedding_model_version_field(self):
        from backend.core.models import WebpageKnowledgeBase

        assert hasattr(WebpageKnowledgeBase, "embedding_model_version")
