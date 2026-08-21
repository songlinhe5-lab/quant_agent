"""
Prompt Governance Service - AGENT-16-NEXT Advanced Features

提供完整的服务层功能：Dashboard API + Golden Dataset + 人工反馈 + LLM-driven evaluation + Vector Store integration.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from hermes_agent.prompt_versioning import (
        ABTestOrchestrator,
        PromptQualityEvaluator,
        PromptQualityMetrics,
        PromptVersionManager,
    )
except ImportError:
    # Fallback for local testing without watchdog
    from hermes_agent.prompt_versioning import (
        PromptQualityEvaluator,
        PromptQualityMetrics,
        PromptVersionManager,
    )


@dataclass
class FeedbackRecord:
    """单条用户反馈记录"""

    prompt_name: str
    version: str
    user_id: str
    rating: int  # -1 (down) to 1 (up), 0 (neutral)
    comment: Optional[str] = None
    created_at: float = field(default_factory=time.time)


@dataclass
class DashboardMetrics:
    """Dashboard 聚合指标"""

    prompt_name: str
    current_version: str
    quality_score: float  # Composite score (0-1)
    trend_7d: List[Tuple[float, float]]  # [(timestamp, score)]
    ab_test_results: List[Dict[str, Any]]  # Active A/B tests
    feedback_stats: Dict[str, float]  # {up_ratio: 0.85, avg_rating: 0.72}
    version_count: int
    last_updated: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_name": self.prompt_name,
            "current_version": self.current_version,
            "quality_score": self.quality_score,
            "trend_7d": [{"ts": ts, "score": score} for ts, score in self.trend_7d],
            "ab_tests": self.ab_test_results,
            "feedback_stats": self.feedback_stats,
            "version_count": self.version_count,
            "last_updated": self.last_updated,
        }


class GoldenDatasetItem:
    """单项回归测试用例"""

    def __init__(self, name: str, input_context: str, expected_output: str, metrics: List[str]):
        self.name = name
        self.input_context = input_context
        self.expected_output = expected_output
        self.metrics = metrics  # ['relevance', 'accuracy', 'completeness']

    def evaluate(self, actual_output: str) -> Dict[str, float]:
        """评估实际输出与期望输出的相似度"""
        # 简化版：基于文本相似度（生产环境可用 LLM-as-a-Judge）
        overlap = self._compute_text_overlap(self.expected_output, actual_output)
        return {metric: overlap for metric in self.metrics}

    def _compute_text_overlap(self, s1: str, s2: str) -> float:
        """计算文本重叠率（Jaccard similarity）"""
        set1 = set(s1.split())
        set2 = set(s2.split())

        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0


class GoldenDatasetRunner:
    """Golden Dataset 回归测试执行器"""

    def __init__(self, dataset_path: str = "prompts/golden_dataset.json"):
        self.dataset_path = Path(dataset_path)
        self.items: List[GoldenDatasetItem] = []
        self.load_dataset()

    def load_dataset(self):
        """加载 Golden Dataset（JSONL 格式）"""
        if not self.dataset_path.exists():
            print(f"⚠️ [GoldenDataset] Dataset not found at {self.dataset_path}, creating sample...")
            self._create_sample_dataset()
            return

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    item = GoldenDatasetItem(
                        name=data["name"],
                        input_context=data["input_context"],
                        expected_output=data["expected_output"],
                        metrics=data.get("metrics", ["relevance", "accuracy"]),
                    )
                    self.items.append(item)
                except Exception as e:
                    print(f"⚠️ [GoldenDataset] Skip malformed line: {e}")

    def _create_sample_dataset(self):
        """创建示例数据集"""
        self.dataset_path.parent.mkdir(parents=True, exist_ok=True)

        samples = [
            {
                "name": "compact_summary_test",
                "input_context": "用户询问 AAPL 股价走势，需要总结过去 5 轮对话中的关键信息",
                "expected_output": "AAPL 股价在过去 5 个交易日内上涨 3.2%，主要受财报超预期驱动...",
                "metrics": ["relevance", "accuracy", "conciseness"],
            },
            {
                "name": "sentiment_analysis_test",
                "input_context": "分析 Twitter 上关于 TSLA 的舆论情绪",
                "expected_output": "TSLA 在 Twitter 上的正面情绪占比 65%，主要围绕新车型发布...",
                "metrics": ["accuracy", "completeness"],
            },
        ]

        with open(self.dataset_path, "w", encoding="utf-8") as f:
            for sample in samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")

        print(f"✅ [GoldenDataset] Created sample dataset with {len(samples)} items")

    def run_regression(self, prompt_content: str) -> Dict[str, Any]:
        """运行回归测试"""
        results = []
        total_score = 0.0

        for item in self.items:
            # Simulate LLM output (production: call actual LLM)
            actual_output = self._simulate_llm_response(prompt_content, item.input_context)

            # Evaluate
            metrics = item.evaluate(actual_output)
            avg_score = sum(metrics.values()) / len(metrics)

            results.append(
                {
                    "test_name": item.name,
                    "actual_output": actual_output[:200],  # Truncate for display
                    "metrics": metrics,
                    "avg_score": avg_score,
                }
            )

            total_score += avg_score

        # Overall pass/fail (threshold 0.7)
        overall_score = total_score / len(self.items) if self.items else 0.0
        passed = overall_score >= 0.7

        return {
            "passed": passed,
            "overall_score": overall_score,
            "items": results,
            "total_tests": len(self.items),
        }

    def _simulate_llm_response(self, prompt: str, context: str) -> str:
        """模拟 LLM 响应（生产环境替换为真实调用）"""
        return f"基于提示词 '{prompt[:50]}...' 生成的响应，针对上下文：{context}"


class FeedbackCollector:
    """用户反馈收集器（thumbs up/down）"""

    def __init__(self, storage_path: str = "logs/prompt_feedback.jsonl"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._in_memory_buffer: List[FeedbackRecord] = []

    def record(self, prompt_name: str, version: str, user_id: str, rating: int, comment: Optional[str] = None):
        """记录反馈"""
        record = FeedbackRecord(
            prompt_name=prompt_name,
            version=version,
            user_id=user_id,
            rating=rating,
            comment=comment,
        )

        # Buffer for batch write
        self._in_memory_buffer.append(record)

        # Auto-flush every 100 records or when full
        if len(self._in_memory_buffer) >= 100:
            self._flush_to_disk()

    def _flush_to_disk(self):
        """批量写入磁盘"""
        if not self._in_memory_buffer:
            return

        with open(self.storage_path, "a", encoding="utf-8") as f:
            for record in self._in_memory_buffer:
                data = {
                    "prompt_name": record.prompt_name,
                    "version": record.version,
                    "user_id": record.user_id,
                    "rating": record.rating,
                    "comment": record.comment,
                    "created_at": record.created_at,
                }
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

        self._in_memory_buffer.clear()

    def get_stats(self, prompt_name: str, version: Optional[str] = None) -> Dict[str, float]:
        """获取统计指标"""
        # Load all feedback for this prompt
        feedbacks = []

        if self.storage_path.exists():
            with open(self.storage_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        if data["prompt_name"] == prompt_name:
                            if version is None or data["version"] == version:
                                feedbacks.append(data)
                    except Exception:
                        continue

        if not feedbacks:
            return {"up_ratio": 0.0, "avg_rating": 0.0, "total_count": 0}

        up_count = sum(1 for f in feedbacks if f["rating"] > 0)
        total_count = len(feedbacks)
        avg_rating = sum(f["rating"] for f in feedbacks) / total_count

        return {
            "up_ratio": up_count / total_count,
            "avg_rating": avg_rating,
            "total_count": total_count,
            "down_ratio": 1.0 - (up_count / total_count),
        }

    def schedule_flush(self):
        """异步刷新（后台线程）"""
        asyncio.create_task(self._flush_to_disk_async())

    async def _flush_to_disk_async(self):
        """异步 flush"""
        await asyncio.get_event_loop().run_in_executor(None, self._flush_to_disk)


class LLMDrivenEvaluator:
    """LLM-driven perplexity evaluation（替代启发式估算）"""

    def __init__(self, llm_client: Any, model: str = "deepseek-pro"):
        self.llm_client = llm_client
        self.model = model

    async def evaluate_perplexity(self, text: str) -> float:
        """通过 LLM 计算困惑度（基于语言模型概率）"""
        try:
            # Split text into tokens and calculate log likelihood
            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个语言模型评估助手。请计算以下文本的困惑度评分（0-10，越低越好）。",
                    },
                    {
                        "role": "user",
                        "content": f"文本：{text}\n\n请只返回一个数字分数（0-10），不要其他内容。",
                    },
                ],
                temperature=0.0,  # Deterministic
                max_tokens=1,
            )

            # Parse numeric score
            score_str = response.choices[0].message.content.strip()
            score = float(score_str[:2])  # Take first 2 chars as number

            # Convert to 0-1 scale (inverse: lower perplexity = higher score)
            normalized_score = 1.0 - (score / 10.0)

            return max(0.0, min(1.0, normalized_score))

        except Exception as e:
            print(f"⚠️ [LLMEvaluator] LLM-based perplexity failed: {e}, fallback to heuristic")
            # Fallback to heuristic estimator
            return self._heuristic_perplexity(text)

    def _heuristic_perplexity(self, text: str) -> float:
        """启发式估算（fallback）"""
        tokens = text.split()
        unique_ratio = len(set(tokens.lower().split())) / len(tokens) if tokens else 1
        return 1.0 - unique_ratio

    async def evaluate_quality(self, prompt: str, output: str, criteria: List[str]) -> Dict[str, float]:
        """LLM 作为 Judge 评估质量"""
        try:
            criteria_str = "\n".join(f"- {c}" for c in criteria)

            response = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的 Prompt 质量评估专家。请根据以下标准对输出进行评分（每项 0-1 分）。",
                    },
                    {
                        "role": "user",
                        "content": f'Prompt:\n{prompt}\n\n输出:\n{output}\n\n评估标准:\n{criteria_str}\n\n请以 JSON 格式返回评分结果：{{"relevance": 0.8, "accuracy": 0.9}}',
                    },
                ],
                temperature=0.1,
                max_tokens=100,
            )

            # Parse JSON result
            content = response.choices[0].message.content.strip()
            scores = json.loads(content)

            return scores

        except Exception as e:
            print(f"⚠️ [LLMEvaluator] LLM-as-Judge failed: {e}")
            return {c: 0.5 for c in criteria}  # Fallback to neutral score


class VectorStoreIntegrator:
    """优质 Prompt 沉淀到向量知识库"""

    def __init__(self, embedding_client: Any, collection_name: str = "prompt_knowledge_base"):
        self.embedding_client = embedding_client
        self.collection_name = collection_name
        self._cache: Dict[str, Dict[str, Any]] = {}

    def index_prompt(
        self,
        name: str,
        version: str,
        content: str,
        metrics: PromptQualityMetrics,
        tags: Optional[List[str]] = None,
    ):
        """将优质 Prompt 索引到向量库"""
        # Build metadata
        metadata = {
            "name": name,
            "version": version,
            "quality_score": metrics.composite_score or 0.0,
            "coherence": metrics.coherence or 0.0,
            "clarity": metrics.clarity or 0.0,
            "tags": tags or [],
            "indexed_at": time.time(),
        }

        # Generate embedding
        embedding = self._generate_embedding(content)

        # Store in memory cache (production: Redis/PostgreSQL)
        key = f"{name}:{version}"
        self._cache[key] = {
            "embedding": embedding,
            "content": content,
            "metadata": metadata,
        }

        print(f"✅ [VectorStore] Indexed {key} (quality: {metadata['quality_score']:.2f})")

    def search_similar(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """搜索相似 Prompt"""
        query_embedding = self._generate_embedding(query)

        # Cosine similarity search
        candidates = []
        for key, data in self._cache.items():
            sim_score = self._cosine_similarity(query_embedding, data["embedding"])

            if sim_score >= min_score:
                candidates.append(
                    {
                        "key": key,
                        "similarity": sim_score,
                        "content": data["content"],
                        "metadata": data["metadata"],
                    }
                )

        # Sort by similarity
        candidates.sort(key=lambda x: x["similarity"], reverse=True)

        return candidates[:top_k]

    def _generate_embedding(self, text: str) -> List[float]:
        """生成嵌入向量（简化版：随机向量 fallback）"""
        try:
            # Production: Use real embedding client
            # response = self.embedding_client.embeddings.create(model="bge-large-zh", input=text)
            # return response.data[0].embedding

            # Fallback: deterministic pseudo-random vector
            import hashlib

            hash_obj = hashlib.sha256(text.encode())
            hash_bytes = hash_obj.digest()

            # Convert to 768-dim vector (matching bge-large-zh)
            vector = []
            for i in range(768):
                byte_idx = (i * 4) % len(hash_bytes)
                value = (hash_bytes[byte_idx] / 255.0) * 2 - 1  # Normalize to [-1, 1]
                vector.append(value)

            return vector

        except Exception:
            # Ultimate fallback
            return [0.0] * 768

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        import math

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


class PromptGovernanceService:
    """统一服务层（对外暴露全局单例）"""

    def __init__(
        self,
        prompt_dir: str = "prompts/compact",
        golden_dataset_path: str = "prompts/golden_dataset.jsonl",
    ):
        self.version_manager = PromptVersionManager(prompt_dir)
        self.golden_runner = GoldenDatasetRunner(golden_dataset_path)
        self.feedback_collector = FeedbackCollector()
        self.vector_store = VectorStoreIntegrator(embedding_client=None)  # Lazy init
        self.llm_evaluator: Optional[LLMDrivenEvaluator] = None

    def initialize_llm(self, llm_client: Any):
        """初始化 LLM 驱动的评估器"""
        self.llm_evaluator = LLMDrivenEvaluator(llm_client)

    async def create_version_with_validation(
        self,
        name: str,
        new_content: str,
        metadata: Optional[Dict] = None,
    ) -> bool:
        """创建新版本并自动验证（Golden Dataset）"""
        # 1. Run Golden Dataset regression test
        validation_result = self.golden_runner.run_regression(new_content)

        if not validation_result["passed"]:
            print(f"❌ [Governance] Golden Dataset failed for {name}: score={validation_result['overall_score']:.2f}")
            return False

        # 2. Create new version
        version = self.version_manager.create_version(name, new_content, metadata)

        # 3. Quality evaluation
        quality_metrics = self._evaluate_quality(new_content)

        # 4. Index to vector store if high quality
        if quality_metrics.composite_score and quality_metrics.composite_score > 0.8:
            self.vector_store.index_prompt(name, version.version, new_content, quality_metrics)

        print(f"✅ [Governance] Version {version.version} created and validated for {name}")
        return True

    def _evaluate_quality(self, prompt: str) -> PromptQualityMetrics:
        """快速质量评估（heuristic fallback）"""
        evaluator = PromptQualityEvaluator()
        return evaluator.evaluate(prompt)

    def record_feedback(
        self,
        prompt_name: str,
        version: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
    ):
        """记录用户反馈"""
        self.feedback_collector.record(prompt_name, version, user_id, rating, comment)

    def get_dashboard_metrics(self, prompt_name: str) -> DashboardMetrics:
        """获取 Dashboard 聚合指标"""
        template = self.version_manager.load_template(prompt_name)
        quality_metrics = self._evaluate_quality(template.current_version)

        # Get feedback stats
        feedback_stats = self.feedback_collector.get_stats(prompt_name)

        return DashboardMetrics(
            prompt_name=prompt_name,
            current_version=template.current_version,
            quality_score=quality_metrics.composite_score or 0.0,
            trend_7d=[],  # Future: historical quality tracking
            ab_test_results=[],  # Future: active A/B tests
            feedback_stats=feedback_stats,
            version_count=len(template.versions),
            last_updated=template.updated_at,
        )


# Global singleton instance (AI-01 coding convention)
_governance_service: Optional[PromptGovernanceService] = None


def get_prompt_governance_service() -> PromptGovernanceService:
    """获取全局 Prompt Governance 服务单例"""
    global _governance_service
    if _governance_service is None:
        _governance_service = PromptGovernanceService()
    return _governance_service


async def initialize_prompt_governance(llm_client: Any):
    """初始化 Prompt Governance 服务（需 LLM 客户端）"""
    global _governance_service
    if _governance_service is None:
        _governance_service = PromptGovernanceService()

    _governance_service.initialize_llm(llm_client)
    print("✅ [PromptGovernance] Service initialized with LLM support")
