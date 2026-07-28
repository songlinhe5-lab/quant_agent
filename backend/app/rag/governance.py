"""
AI-04 · RAG 知识库治理服务

- 分类 TTL 清理 (已在 screener_service 中实现)
- Embedding 模型版本管理: 启动时检测版本不一致，触发全量重建
- 检索质量监控: 连续低相似度告警
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 检索质量阈值
SIMILARITY_THRESHOLD = 0.6
LOW_QUALITY_STREAK = 10  # 连续 N 次低相似度触发告警


class RAGGovernanceService:
    """RAG 知识库治理服务"""

    def __init__(self):
        self._low_similarity_streak: int = 0
        self._total_retrievals: int = 0
        self._low_similarity_count: int = 0

    async def check_embedding_version(self) -> Optional[str]:
        """
        检查 DB 中已有记录的 embedding 模型版本是否与当前配置一致。

        Returns:
            None: 版本一致或无数据
            str: 不一致的旧版本号 (需要触发重建)
        """
        from backend.core.config import settings

        current_version = settings.embedding_model

        def _check():
            from sqlalchemy import text

            from backend.core.database import engine

            try:
                with engine.connect() as conn:
                    # 检查表是否存在
                    table_exists = conn.execute(
                        text(
                            "SELECT EXISTS (SELECT FROM information_schema.tables "
                            "WHERE table_name = 'webpage_knowledge_base')"
                        )
                    ).scalar()
                    if not table_exists:
                        return None

                    # 查询是否存在不同版本的记录
                    result = conn.execute(
                        text(
                            "SELECT DISTINCT embedding_model_version "
                            "FROM webpage_knowledge_base "
                            "WHERE embedding_model_version IS NOT NULL "
                            "AND embedding_model_version != :current "
                            "LIMIT 1"
                        ),
                        {"current": current_version},
                    ).fetchone()
                    return result[0] if result else None
            except Exception as e:
                logger.warning(f"[RAGGovernance] 检查 embedding 版本失败: {e}")
                return None

        import asyncio

        return await asyncio.to_thread(_check)

    async def trigger_embedding_rebuild(self) -> Dict[str, Any]:
        """
        触发 embedding 全量重建: 删除旧版本向量，标记需要重新 embedding。

        实际重建需要重新调用 embedding API，这里仅清理旧数据并记录状态。
        """
        from backend.core.config import settings

        current_version = settings.embedding_model

        def _rebuild():
            from sqlalchemy import text

            from backend.core.database import engine

            try:
                with engine.begin() as conn:
                    # 删除旧版本的记录 (而非更新向量，因为无法原地 re-embed)
                    result = conn.execute(
                        text(
                            "DELETE FROM webpage_knowledge_base "
                            "WHERE embedding_model_version IS NOT NULL "
                            "AND embedding_model_version != :current"
                        ),
                        {"current": current_version},
                    )
                    deleted = result.rowcount
                logger.info(f"[RAGGovernance] Embedding 重建完成，删除 {deleted} 条旧版本记录")
                return {"status": "success", "deleted_count": deleted, "new_version": current_version}
            except Exception as e:
                logger.error(f"[RAGGovernance] Embedding 重建失败: {e}")
                return {"status": "error", "message": str(e)}

        import asyncio

        result = await asyncio.to_thread(_rebuild)

        # 写入 Redis 状态
        try:
            from backend.core.redis_client import redis_client

            await redis_client.set(
                "quant:embedding:rebuild_status",
                str(result),
                ex=86400,  # 24 小时过期
            )
        except Exception:
            pass

        return result

    def record_retrieval_similarity(self, max_similarity: float) -> bool:
        """
        记录一次检索的最高相似度分数。

        Returns:
            True: 触发告警 (连续低相似度)
            False: 正常
        """
        self._total_retrievals += 1

        if max_similarity < SIMILARITY_THRESHOLD:
            self._low_similarity_streak += 1
            self._low_similarity_count += 1

            if self._low_similarity_streak >= LOW_QUALITY_STREAK:
                logger.warning(
                    f"[RAGGovernance] 检索质量告警: 连续 {self._low_similarity_streak} 次 "
                    f"最高相似度 < {SIMILARITY_THRESHOLD}，当前值: {max_similarity:.4f}"
                )
                # 重置计数器防止持续告警
                self._low_similarity_streak = 0
                return True
        else:
            # 高相似度重置连续计数
            self._low_similarity_streak = 0

        return False

    def get_quality_stats(self) -> Dict[str, Any]:
        """返回检索质量统计信息"""
        low_rate = self._low_similarity_count / self._total_retrievals if self._total_retrievals > 0 else 0.0
        return {
            "total_retrievals": self._total_retrievals,
            "low_similarity_count": self._low_similarity_count,
            "low_similarity_rate": round(low_rate, 4),
            "current_streak": self._low_similarity_streak,
            "threshold": SIMILARITY_THRESHOLD,
        }


# 全局单例
rag_governance = RAGGovernanceService()
