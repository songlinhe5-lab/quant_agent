"""
Prompt Governance Approval API Router

Human-in-the-loop 审批流程 API 端点。
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

try:
    from backend.core.database import get_db_session
    from backend.services.prompt.approval_service import (
        ApprovalRequest,
        DeploymentEnvironment,
        PromptApprovalService,
        RollbackRequest,
        get_prompt_approval_service,
    )
except ImportError:
    get_db_session = None
    DeploymentEnvironment = None


router = APIRouter(prefix="/prompt-governance/approval", tags=["Prompt Approval"])


# Request/Response Models
class ApproveVersionRequest(BaseModel):
    """批准版本请求"""

    audit_id: str
    comment: Optional[str] = Field(default=None, max_length=500)
    user_id: str = Field(..., description="当前登录用户 ID")
    username: str = Field(..., description="当前登录用户名")


class RejectVersionRequest(BaseModel):
    """拒绝版本请求"""

    audit_id: str
    reason: str = Field(..., max_length=1000)
    user_id: str
    username: str


class DeployRequest(BaseModel):
    """部署请求"""

    audit_id: str
    environment: str = Field(default="production", description="staging|production|canary")
    user_id: str
    username: str


class RollbackRequestPayload(BaseModel):
    """回滚请求"""

    prompt_name: str
    target_version: str
    reason: str = Field(..., max_length=500)
    user_id: str
    username: str
    deploy_environment: str = Field(default="production")


class PendingApprovalResponse(BaseModel):
    """待审批记录响应"""

    id: str
    prompt_name: str
    from_version: str
    to_version: str
    quality_score_at_approval: float
    created_at: str
    reviewer_username: Optional[str] = None

    class Config:
        from_attributes = True


class ApprovalHistoryResponse(BaseModel):
    """审批历史记录"""

    id: str
    status: str
    reviewer_user_id: Optional[str]
    reviewer_username: Optional[str]
    approved_at: Optional[str]
    rejected_at: Optional[str]
    deployed_to_production: bool
    deployed_to_production_at: Optional[str]

    class Config:
        from_attributes = True


# API Endpoints
@router.get("/pending", response_model=List[PendingApprovalResponse])
async def list_pending_approvals(
    db: Session = Depends(get_db_session),
    prompt_name: Optional[str] = None,
    limit: int = 20,
):
    """获取待审批的 Prompt 版本列表"""
    service = get_prompt_approval_service(db)

    try:
        audits = service.get_pending_approvals(prompt_name=prompt_name, limit=limit)

        return [
            {
                "id": a.id,
                "prompt_name": a.prompt_name,
                "from_version": a.from_version,
                "to_version": a.to_version,
                "quality_score_at_approval": a.quality_score_at_approval or 0.0,
                "created_at": a.created_at.isoformat(),
                "reviewer_username": a.reviewer_username,
            }
            for a in audits
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/approve", response_model=Dict[str, str])
async def approve_version(
    request: ApproveVersionRequest,
    db: Session = Depends(get_db_session),
):
    """批准版本（Human-in-the-loop）"""
    service = get_prompt_approval_service(db)

    try:
        audit = service.approve_version(
            audit_id=request.audit_id,
            user_id=request.user_id,
            username=request.username,
            comment=request.comment,
        )

        if not audit:
            raise HTTPException(status_code=404, detail="Audit record not found")

        return {"status": "approved", "audit_id": audit.id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject", response_model=Dict[str, str])
async def reject_version(
    request: RejectVersionRequest,
    db: Session = Depends(get_db_session),
):
    """拒绝版本"""
    service = get_prompt_approval_service(db)

    try:
        audit = service.reject_version(
            audit_id=request.audit_id,
            user_id=request.user_id,
            comment=request.reason,
        )

        if not audit:
            raise HTTPException(status_code=404, detail="Audit record not found")

        return {"status": "rejected", "audit_id": audit.id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deploy/staging", response_model=Dict[str, str])
async def deploy_to_staging(
    request: DeployRequest,
    db: Session = Depends(get_db_session),
):
    """部署到测试环境"""
    service = get_prompt_approval_service(db)

    try:
        audit = service.deploy_to_staging(request.audit_id)

        if not audit:
            raise HTTPException(status_code=404, detail="Audit record not found")

        return {"status": "deployed", "environment": "staging", "audit_id": audit.id}

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/deploy/production", response_model=Dict[str, str])
async def deploy_to_production(
    request: DeployRequest,
    db: Session = Depends(get_db_session),
):
    """部署到生产环境"""
    service = get_prompt_approval_service(db)

    try:
        environment = DeploymentEnvironment.PRODUCTION
        if request.environment == "canary":
            environment = DeploymentEnvironment.CANARY

        audit = service.deploy_to_production(request.audit_id, environment)

        if not audit:
            raise HTTPException(status_code=404, detail="Audit record not found")

        return {
            "status": "deployed",
            "environment": request.environment,
            "audit_id": audit.id,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback", response_model=Dict[str, str])
async def rollback_version(
    request: RollbackRequestPayload,
    db: Session = Depends(get_db_session),
):
    """执行回滚操作（一键回滚按钮）"""
    service = get_prompt_approval_service(db)

    try:
        # Determine deployment environment
        env = DeploymentEnvironment.PRODUCTION
        if request.deploy_environment == "staging":
            env = DeploymentEnvironment.STAGING
        elif request.deploy_environment == "canary":
            env = DeploymentEnvironment.CANARY

        rollback_req = RollbackRequest(
            prompt_name=request.prompt_name,
            target_version=request.target_version,
            performed_by_user_id=request.user_id,
            performed_by_username=request.username,
            reason=request.reason,
            deploy_environment=env,
        )

        deployment_log = service.rollback_version(rollback_req)

        if not deployment_log:
            raise HTTPException(status_code=404, detail="Rollback failed")

        return {
            "status": "rolled_back",
            "target_version": request.target_version,
            "deployment_log_id": deployment_log.id,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_name}/history", response_model=List[ApprovalHistoryResponse])
async def get_approval_history(
    prompt_name: str,
    db: Session = Depends(get_db_session),
    limit: int = 50,
):
    """获取 Prompt 版本的审批历史"""
    service = get_prompt_approval_service(db)

    try:
        audits = service.get_approval_history(prompt_name=prompt_name, limit=limit)

        return [
            {
                "id": a.id,
                "status": a.status.value,
                "reviewer_user_id": a.reviewer_user_id,
                "reviewer_username": a.reviewer_username,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
                "rejected_at": a.rejected_at.isoformat() if a.rejected_at else None,
                "deployed_to_production": a.deployed_to_production,
                "deployed_to_production_at": (
                    a.deployed_to_production_at.isoformat() if a.deployed_to_production_at else None
                ),
            }
            for a in audits
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{prompt_name}/deployments", response_model=List[Dict[str, Any]])
async def get_deployment_history(
    prompt_name: str,
    db: Session = Depends(get_db_session),
    limit: int = 50,
):
    """获取 Prompt 版本的部署历史"""
    service = get_prompt_approval_service(db)

    try:
        deployments = service.get_recent_deployments(prompt_name=prompt_name, limit=limit)

        return [d.to_dict() for d in deployments]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Manual trigger endpoint (for testing)
@router.post("/manual/create-audit")
async def manual_create_audit_record(
    prompt_name: str,
    from_version: str,
    to_version: str,
    quality_score: float = 0.85,
):
    """手动创建审批记录（用于测试）"""
    try:
        service = get_prompt_approval_service()

        request = ApprovalRequest(
            prompt_name=prompt_name,
            from_version=from_version,
            to_version=to_version,
            reviewer_user_id="system_test",
            reviewer_username="test_system",
            quality_score=quality_score,
            comment="Manual creation for testing",
        )

        audit = service.create_audit_record(request)

        return {
            "status": "created",
            "audit_id": audit.id if audit else None,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
