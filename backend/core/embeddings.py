"""
统一 Embedding 生成工具 (AI-04 RAG 知识库)。

设计原则:
- 单一入口: 全局知识库的「写入(fetch_webpage)」与「检索(search_global_knowledge)」
  必须共用同一个 embedding 函数，保证向量空间一致，否则余弦检索命中率崩塌。
- 维度契约: 生成向量维度必须与 backend/core/models.WebpageKnowledgeBase.embedding
  (Vector(EMBEDDING_DIM)，默认 1024) 严格对齐，因此以 EMBEDDING_MODEL 环境变量
  为准 (默认 BAAI/bge-large-zh-v1.5，输出 1024 维)，不再硬编码 MiniLM(384 维)。
- 零幻觉: 生成失败返回 [] 而非假装成功，调用方据此降级。
"""

import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

_BATCH_SIZE = 32  # 远程 API 单次批大小上限保护


# Embedding 配置统一从 pydantic Settings 读取（Settings 加载 .env）。
# 修复：此前用裸 os.getenv，Hermes CLI(scripts/run_cli.py) 未 load_dotenv 导致
# EMBEDDING_API_KEY 读不到 → 走本地模型 → 返回空 → 知识库写入静默失败。
def _embed_settings() -> tuple:
    """返回 (model, api_key, base_url)。优先 pydantic settings(已加载 .env)，回退裸 env。"""
    try:
        from backend.core.config import settings

        return (
            settings.embedding_model,
            settings.embedding_api_key,
            settings.embedding_base_url,
        )
    except Exception:
        # pydantic settings 不可用/校验失败时回退裸 env（保持向后兼容）
        return (
            os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5"),
            os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
            os.getenv("EMBEDDING_BASE_URL"),
        )


def _embed_api(texts: List[str], model: str, api_key: str, base_url: Optional[str]) -> Optional[List[List[float]]]:
    """通过 OpenAI 兼容 Embedding API 生成向量。"""
    import requests

    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    out: List[List[float]] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i : i + _BATCH_SIZE]
        try:
            res = requests.post(
                f"{base}/embeddings",
                headers=headers,
                json={"input": batch, "model": model},
                timeout=30,
            )
            if res.status_code != 200:
                logger.error(f"[Embeddings] API 失败 {res.status_code}: {res.text[:200]}")
                return None
            out.extend([d["embedding"] for d in res.json().get("data", [])])
        except Exception as e:
            logger.error(f"[Embeddings] API 异常: {e}")
            return None
    return out


def _embed_local(texts: List[str], model: str) -> Optional[List[List[float]]]:
    """通过本地 sentence_transformers 生成向量。"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning("[Embeddings] 未安装 sentence_transformers 且未配置 EMBEDDING_API_KEY")
        return None
    try:
        st = SentenceTransformer(model)
        return st.encode(texts, normalize_embeddings=True).tolist()
    except Exception as e:
        logger.error(f"[Embeddings] 本地模型 {model} 加载/编码失败: {e}")
        return None


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    批量生成文本向量。维度由 EMBEDDING_MODEL 决定 (默认 bge-large-zh-v1.5 = 1024)。

    Returns:
        成功: List[vector]，长度与 texts 一致。
        失败/不可用: 空列表 [] (调用方必须据此降级，严禁假装成功)。
    """
    if not texts:
        return []

    model, api_key, base_url = _embed_settings()

    if api_key:
        vecs = _embed_api(texts, model, api_key, base_url)
    else:
        vecs = _embed_local(texts, model)

    if not vecs or len(vecs) != len(texts):
        return []
    return vecs
