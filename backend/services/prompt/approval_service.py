"""
Prompt Governance Approval Service

Human-in-the-loop 审批服务层，集成 AI-01 singletons + audit trail。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

try:
    from backend.core.database import get_db_session
    from backend.core.models.prompt_governance import (
        ApprovalStatus,
        DeploymentEnvironment,
        PromptApprovalAudit,
        PromptDeploymentLog,
    )
except ImportError:
    # Fallback for local testing
    PromptApprovalAudit = None
    ApprovalStatus = None
    DeploymentEnvironment = None
    get_db_session = None


@dataclass
class ApprovalRequest:
    """审批请求数据"""

    prompt_name: str
    from_version: str
    to_version: str
    reviewer_user_id: str
    reviewer_username: str
    quality_score: float
    comment: Optional[str] = None


@dataclass
class RollbackRequest:
    """回滚请求数据"""

    prompt_name: str
    target_version: str
    performed_by_user_id: str
    performed_by_username: str
    reason: str
    deploy_environment: DeploymentEnvironment = DeploymentEnvironment.PRODUCTION


class PromptApprovalService:
    """Prompt 审批服务（Human-in-the-loop）"""

    def __init__(self, db_session: Optional[Session] = None):
        self.db_session = db_session

    def _get_session(self) -> Session:
        """获取数据库会话（支持手动注入或自动获取）"""
        if self.db_session:
            return self.db_session

        if get_db_session is None:
            raise RuntimeError("Database session required but not available")

        return next(get_db_session())

    def create_audit_record(self, request: ApprovalRequest) -> PromptApprovalAudit:
        """创建审计记录"""
        if PromptApprovalAudit is None:
            print("⚠️ [ApprovalService] Database model not available, skipping audit record")
            return None

        with self._get_session() as session:
            audit = PromptApprovalAudit(
                prompt_name=request.prompt_name,
                from_version=request.from_version,
                to_version=request.to_version,
                reviewer_user_id=request.reviewer_user_id,
                reviewer_username=request.reviewer_username,
                status=ApprovalStatus.PENDING,
                quality_score_at_approval=request.quality_score,
                deployed_to_staging=False,
                deployed_to_production=False,
            )

            session.add(audit)
            session.commit()
            session.refresh(audit)

            print(f"✅ [ApprovalService] Created audit record: {audit.id}")
            return audit

    def approve_version(self, audit_id: str, user_id: str, username: str, comment: Optional[str] = None):
        """批准版本"""
        if PromptApprovalAudit is None:
            return None

        with self._get_session() as session:
            audit = session.query(PromptApprovalAudit).filter(PromptApprovalAudit.id == audit_id).first()

            if not audit:
                raise ValueError(f"Audit record not found: {audit_id}")

            if audit.status != ApprovalStatus.PENDING:
                raise ValueError(f"Audit already {audit.status.value}")

            audit.approve(user_id, username, comment)
            session.commit()

            print(f"✅ [ApprovalService] Approved version: {audit.prompt_name} v{audit.to_version}")
            return audit

    def reject_version(self, audit_id: str, user_id: str, comment: str):
        """拒绝版本"""
        if PromptApprovalAudit is None:
            return None

        with self._get_session() as session:
            audit = session.query(PromptApprovalAudit).filter(PromptApprovalAudit.id == audit_id).first()

            if not audit:
                raise ValueError(f"Audit record not found: {audit_id}")

            audit.reject(user_id, comment)
            session.commit()

            print(f"❌ [ApprovalService] Rejected version: {audit.prompt_name} v{audit.to_version}")
            return audit

    def deploy_to_staging(self, audit_id: str):
        """部署到测试环境"""
        if PromptApprovalAudit is None:
            return None

        with self._get_session() as session:
            audit = session.query(PromptApprovalAudit).filter(PromptApprovalAudit.id == audit_id).first()

            if not audit:
                raise ValueError(f"Audit record not found: {audit_id}")

            if audit.status != ApprovalStatus.APPROVED:
                raise ValueError(f"Cannot deploy without approval. Status: {audit.status.value}")

            audit.deploy_to_staging()
            session.commit()

            print(f"✅ [ApprovalService] Deployed to staging: {audit.prompt_name} v{audit.to_version}")
            return audit

    def deploy_to_production(
        self, audit_id: str, environment: DeploymentEnvironment = DeploymentEnvironment.PRODUCTION
    ):
        """部署到生产环境"""
        if PromptApprovalAudit is None:
            return None

        with self._get_session() as session:
            audit = session.query(PromptApprovalAudit).filter(PromptApprovalAudit.id == audit_id).first()

            if not audit:
                raise ValueError(f"Audit record not found: {audit_id}")

            if audit.status != ApprovalStatus.APPROVED:
                raise ValueError(f"Cannot deploy without approval. Status: {audit.status.value}")

            audit.deploy_to_production(environment)
            session.commit()

            print(f"🚀 [ApprovalService] Deployed to production: {audit.prompt_name} v{audit.to_version}")
            return audit

    def rollback_version(self, request: RollbackRequest):
        """执行回滚操作"""
        if PromptApprovalAudit is None:
            return None

        # 1. Create audit log for rollback
        with self._get_session() as session:
            deployment_log = PromptDeploymentLog(
                prompt_name=request.prompt_name,
                version_before=None,  # Will be filled after reading current state
                version_after=request.target_version,
                action_type="rollback",
                performed_by_user_id=request.performed_by_user_id,
                performed_by_username=request.performed_by_username,
                reason=request.reason,
                notes=f"Rolled back to {request.target_version}",
                environment=request.deploy_environment,
            )

            session.add(deployment_log)
            session.commit()

            print(f"↩️ [ApprovalService] Rollback initiated: {request.prompt_name} → {request.target_version}")
            return deployment_log

    def create_deployment_log(
        self,
        prompt_name: str,
        version_before: Optional[str],
        version_after: str,
        action_type: str,
        performed_by_user_id: str,
        performed_by_username: str,
        reason: str = "",
        notes: str = "",
        success: bool = True,
        error_message: Optional[str] = None,
    ):
        """创建部署日志"""
        if PromptDeploymentLog is None:
            return None

        with self._get_session() as session:
            log = PromptDeploymentLog(
                prompt_name=prompt_name,
                version_before=version_before,
                version_after=version_after,
                action_type=action_type,
                performed_by_user_id=performed_by_user_id,
                performed_by_username=performed_by_username,
                reason=reason,
                notes=notes,
                success=success,
                error_message=error_message,
            )

            session.add(log)
            session.commit()

            return log

    def get_pending_approvals(
        self,
        prompt_name: Optional[str] = None,
        limit: int = 20,
    ) -> List[PromptApprovalAudit]:
        """获取待审批记录"""
        if PromptApprovalAudit is None:
            return []

        with self._get_session() as session:
            query = session.query(PromptApprovalAudit).filter(PromptApprovalAudit.status == ApprovalStatus.PENDING)

            if prompt_name:
                query = query.filter(PromptApprovalAudit.prompt_name == prompt_name)

            audits = query.order_by(PromptApprovalAudit.created_at.desc()).limit(limit).all()

            return audits

    def get_approval_history(
        self,
        prompt_name: str,
        limit: int = 50,
    ) -> List[PromptApprovalAudit]:
        """获取审批历史记录"""
        if PromptApprovalAudit is None:
            return []

        with self._get_session() as session:
            audits = (
                session.query(PromptApprovalAudit)
                .filter(PromptApprovalAudit.prompt_name == prompt_name)
                .order_by(PromptApprovalAudit.created_at.desc())
                .limit(limit)
                .all()
            )

            return audits

    def get_recent_deployments(
        self,
        prompt_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[PromptDeploymentLog]:
        """获取最近部署记录"""
        if PromptDeploymentLog is None:
            return []

        with self._get_session() as session:
            query = session.query(PromptDeploymentLog)

            if prompt_name:
                query = query.filter(PromptDeploymentLog.prompt_name == prompt_name)

            deployments = query.order_by(PromptDeploymentLog.created_at.desc()).limit(limit).all()

            return deployments


# Global singleton instance
_service_instance: Optional[PromptApprovalService] = None


def get_prompt_approval_service(db_session: Optional[Session] = None) -> PromptApprovalService:
    """获取全局 Prompt Approval Service 单例（AI-01 convention）"""
    global _service_instance
    if _service_instance is None:
        _service_instance = PromptApprovalService(db_session)
    else:
        # Update session if provided
        if db_session:
            _service_instance.db_session = db_session
    return _service_instance


async def initialize_approval_system():
    """初始化审批系统"""
    try:
        service = get_prompt_approval_service()

        pending = service.get_pending_approvals()

        print(f"✅ [ApprovalSystem] Initialized with {len(pending)} pending approvals")

    except Exception as e:
        print(f"⚠️ [ApprovalSystem] Initialization failed: {e}")
