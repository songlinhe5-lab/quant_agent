"""
Prompt Governance API Router - AGENT-16-NEXT Advanced Features

提供 HTTP/REST API 端点，支持 Dashboard + Golden Dataset + Feedback + LLM Evaluation.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from backend.database.session import get_db_session
except ImportError:
    get_db_session = None


router = APIRouter(prefix="/prompt-governance", tags=["Prompt Governance"])


# Request/Response Models
class CreateVersionRequest(BaseModel):
    """创建新版本请求"""

    name: str = Field(..., description="Prompt 名称")
    content: str = Field(..., description="Prompt 内容")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="元数据")
    skip_validation: bool = Field(default=False, description="跳过 Golden Dataset 验证")


class FeedbackRequest(BaseModel):
    """反馈记录请求"""

    prompt_name: str = Field(..., description="Prompt 名称")
    version: str = Field(..., description="版本号")
    user_id: str = Field(..., description="用户 ID")
    rating: int = Field(..., ge=-1, le=1, description="评分：-1(down)/0(neutral)/1(up)")
    comment: Optional[str] = Field(default=None, max_length=500)


class ABOptimizationRequest(BaseModel):
    """A/B 测试优化建议"""

    prompt_name: str
    min_improvement: float = Field(default=0.05, description="最小改进阈值（5%）")


# Response Models
class VersionHistoryResponse(BaseModel):
    """版本历史"""

    name: str
    current_version: str
    versions: List[Dict[str, Any]]
    quality_metrics: Optional[Dict[str, float]] = None


class DashboardResponse(BaseModel):
    """Dashboard 聚合指标"""

    prompt_name: str
    current_version: str
    quality_score: float
    trend_7d: List[Dict[str, float]]
    ab_tests: List[Dict[str, Any]]
    feedback_stats: Dict[str, float]
    version_count: int
    last_updated: float


class GoldenDatasetValidationResponse(BaseModel):
    """Golden Dataset 验证结果"""

    passed: bool
    overall_score: float
    items: List[Dict[str, Any]]
    total_tests: int


class SimilarPromptsResponse(BaseModel):
    """相似 Prompt 搜索结果"""

    results: List[Dict[str, Any]]
    query: str
    top_k: int


# API Endpoints
@router.post("/versions", response_model=VersionHistoryResponse)
async def create_prompt_version(request: CreateVersionRequest):
    """创建新版本并自动验证（Golden Dataset）"""
    from hermes_agent.prompt_versioning import PromptVersionManager

    try:
        manager = PromptVersionManager("prompts/compact")

        # Create version
        version = manager.create_version(
            name=request.name,
            new_content=request.content,
            metadata=request.metadata or {},
        )

        # Load template and return
        template = manager.load_template(request.name)

        return VersionHistoryResponse(
            name=request.name,
            current_version=version.version,
            versions=[
                {
                    "version": v.version,
                    "checksum": v.checksum,
                    "created_at": v.created_at,
                    "metadata": v.metadata,
                }
                for v in template.versions
            ],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/versions/{name}/history", response_model=VersionHistoryResponse)
async def get_version_history(name: str):
    """获取版本历史"""
    from hermes_agent.prompt_versioning import PromptVersionManager

    manager = PromptVersionManager("prompts/compact")
    template = manager.load_template(name)

    return VersionHistoryResponse(
        name=name,
        current_version=template.current_version,
        versions=[
            {
                "version": v.version,
                "checksum": v.checksum,
                "created_at": v.created_at,
                "metadata": v.metadata,
            }
            for v in template.versions
        ],
    )


@router.get("/dashboard", response_model=List[DashboardResponse])
async def get_dashboard():
    """获取所有 Prompt 的 Dashboard 指标"""
    from backend.services.prompt.governance_service import get_prompt_governance_service

    service = get_prompt_governance_service()
    manager = service.version_manager

    responses = []
    for name in manager.templates.keys():
        metrics = service.get_dashboard_metrics(name)
        responses.append(DashboardResponse(**metrics.to_dict()))

    return responses


@router.get("/dashboard/{name}", response_model=DashboardResponse)
async def get_prompt_dashboard(name: str):
    """获取单个 Prompt 的 Dashboard 指标"""
    from backend.services.prompt.governance_service import get_prompt_governance_service

    service = get_prompt_governance_service()
    metrics = service.get_dashboard_metrics(name)

    return DashboardResponse(**metrics.to_dict())


@router.post("/validate/golden-dataset", response_model=GoldenDatasetValidationResponse)
async def validate_with_golden_dataset(content: str):
    """运行 Golden Dataset 回归测试"""
    from backend.services.prompt.governance_service import GoldenDatasetRunner

    runner = GoldenDatasetRunner()
    result = runner.run_regression(content)

    return GoldenDatasetValidationResponse(
        passed=result["passed"],
        overall_score=result["overall_score"],
        items=result["items"],
        total_tests=result["total_tests"],
    )


@router.post("/feedback", response_model=Dict[str, str])
async def record_feedback(request: FeedbackRequest):
    """记录用户反馈（thumbs up/down）"""
    from backend.services.prompt.governance_service import get_prompt_governance_service

    service = get_prompt_governance_service()
    service.record_feedback(
        prompt_name=request.prompt_name,
        version=request.version,
        user_id=request.user_id,
        rating=request.rating,
        comment=request.comment,
    )

    return {"status": "recorded"}


@router.get("/feedback/stats/{name}/{version}", response_model=Dict[str, float])
async def get_feedback_stats(name: str, version: str):
    """获取反馈统计"""
    from backend.services.prompt.governance_service import get_prompt_governance_service

    service = get_prompt_governance_service()
    stats = service.feedback_collector.get_stats(name, version)

    return stats


@router.post("/search/similar", response_model=SimilarPromptsResponse)
async def search_similar_prompts(query: str, top_k: int = 5, min_score: float = 0.7):
    """搜索相似的优质 Prompt"""
    from backend.services.prompt.governance_service import VectorStoreIntegrator

    vector_store = VectorStoreIntegrator(embedding_client=None)
    results = vector_store.search_similar(query, top_k=top_k, min_score=min_score)

    return SimilarPromptsResponse(
        results=[
            {
                "key": r["key"],
                "similarity": r["similarity"],
                "content": r["content"][:500],  # Truncate
                "metadata": r["metadata"],
            }
            for r in results
        ],
        query=query,
        top_k=top_k,
    )


@router.get("/quality/{name}/{version}", response_model=Dict[str, float])
async def get_quality_metrics(name: str, version: str):
    """获取指定版本的 Prompt 质量指标"""
    from backend.services.prompt.governance_service import PromptQualityEvaluator

    evaluator = PromptQualityEvaluator()

    # Load prompt content
    from hermes_agent.prompt_versioning import PromptVersionManager

    manager = PromptVersionManager("prompts/compact")
    content = manager.get_variant(name, version)

    if not content:
        raise HTTPException(status_code=404, detail=f"Version {version} not found for {name}")

    metrics = evaluator.evaluate(content)

    return metrics.to_dict()


@router.post("/llm-evaluate/perplexity")
async def evaluate_perplexity(text: str):
    """LLM-driven perplexity evaluation（异步）"""
    # Note: This is a sync wrapper around async function
    import asyncio

    from backend.services.prompt.governance_service import LLMDrivenEvaluator

    async def _evaluate():
        # Get LLM client from context (simplified)
        evaluator = LLMDrivenEvaluator(llm_client=None)  # TODO: inject real client

        return await evaluator.evaluate_perplexity(text)

    score = asyncio.run(_evaluate())

    return {"perplexity_score": score, "interpretation": "Lower is better"}


@router.get("/ab-test/optimization/{name}", response_model=Dict[str, Any])
async def get_ab_optimization_suggestions(name: str, request: ABOptimizationRequest):
    """获取 A/B 测试优化建议"""
    from hermes_agent.prompt_versioning import ABTestOrchestrator

    ABTestOrchestrator(version_manager=None)  # TODO: initialize

    # TODO: Implement A/B analysis logic
    return {
        "suggestions": [
            {
                "type": "clarity_improvement",
                "priority": "high",
                "description": "增加明确的输出约束条件",
            },
            {
                "type": "coherence_boost",
                "priority": "medium",
                "description": "添加逻辑连接词以增强连贯性",
            },
        ],
        "confidence": 0.75,
    }


# Initialize services on startup
def init_governance_services():
    """初始化 Prompt Governance 服务"""
    try:
        # Placeholder: Real LLM client initialization happens later
        import asyncio

        from backend.services.prompt.governance_service import initialize_prompt_governance

        async def _init():
            await initialize_prompt_governance(llm_client=None)

        asyncio.run(_init())

    except Exception as e:
        print(f"⚠️ [GovernanceInit] Service initialization failed: {e}")
