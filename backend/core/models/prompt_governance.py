"""
Prompt Approval Audit Trail Model

存储所有 Prompt 版本的审批记录、回滚操作和生产部署审计。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ApprovalStatus(Enum):
    """审批状态枚举"""

    PENDING = "pending"  # 等待审批
    APPROVED = "approved"  # 已批准
    REJECTED = "rejected"  # 已拒绝
    ROLLED_BACK = "rolled_back"  # 已回滚


class DeploymentEnvironment(Enum):
    """部署环境枚举"""

    STAGING = "staging"  # 测试环境
    PRODUCTION = "production"  # 生产环境
    CANARY = "canary"  # 金丝雀发布


class PromptApprovalAudit(Base):
    """Prompt 审批审计表"""

    __tablename__ = "prompt_approval_audit"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 基础信息
    prompt_name = Column(String(255), nullable=False, index=True)
    from_version = Column(String(50), nullable=False)
    to_version = Column(String(50), nullable=False)

    # 审批信息
    reviewer_user_id = Column(String(100), nullable=True)  # None = automated approval
    reviewer_username = Column(String(100), nullable=True)
    status = Column(SQLAlchemyEnum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False)
    comment = Column(Text, nullable=True)

    # 质量指标快照
    quality_score_at_approval = Column(Float, nullable=True)  # Score when approved

    # 部署信息
    deployed_to_staging = Column(Boolean, default=False, nullable=False, index=True)
    deployed_to_production = Column(Boolean, default=False, nullable=False, index=True)
    deployment_environment = Column(SQLAlchemyEnum(DeploymentEnvironment), nullable=True)
    deployed_at = Column(DateTime(timezone=True), nullable=True)

    # 时间戳
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    deployed_to_production_at = Column(DateTime(timezone=True), nullable=True)

    # 索引
    __table_args__ = (
        Index(
            "idx_prompt_version_status",
            "prompt_name",
            "to_version",
            "status",
        ),
        Index("idx_deployed_to_production", "deployed_to_production"),
    )

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "prompt_name": self.prompt_name,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "reviewer_user_id": self.reviewer_user_id,
            "reviewer_username": self.reviewer_username,
            "status": self.status.value if isinstance(self.status, ApprovalStatus) else self.status,
            "comment": self.comment,
            "quality_score_at_approval": self.quality_score_at_approval,
            "deployed_to_staging": self.deployed_to_staging,
            "deployed_to_production": self.deployed_to_production,
            "deployment_environment": (self.deployment_environment.value if self.deployment_environment else None),
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "deployed_to_production_at": (
                self.deployed_to_production_at.isoformat() if self.deployed_to_production_at else None
            ),
        }

    def approve(self, user_id: str, username: str, comment: Optional[str] = None):
        """标记为已批准"""
        self.status = ApprovalStatus.APPROVED
        self.reviewer_user_id = user_id
        self.reviewer_username = username
        self.comment = comment
        self.approved_at = datetime.now(timezone.utc)

    def reject(self, user_id: str, comment: str):
        """标记为已拒绝"""
        self.status = ApprovalStatus.REJECTED
        self.reviewer_user_id = user_id
        self.comment = comment
        self.rejected_at = datetime.now(timezone.utc)

    def deploy_to_staging(self):
        """部署到测试环境"""
        self.deployed_to_staging = True
        self.deployment_environment = DeploymentEnvironment.STAGING
        self.deployed_at = datetime.now(timezone.utc)

    def deploy_to_production(
        self,
        environment: DeploymentEnvironment = DeploymentEnvironment.PRODUCTION,
    ):
        """部署到生产环境"""
        self.deployed_to_production = True
        self.deployment_environment = environment
        self.deployed_to_production_at = datetime.now(timezone.utc)


class PromptDeploymentLog(Base):
    """Prompt 部署日志（独立于审批的完整历史记录）"""

    __tablename__ = "prompt_deployment_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    prompt_name = Column(String(255), nullable=False, index=True)
    version_before = Column(String(50))
    version_after = Column(String(50), nullable=False)

    action_type = Column(String(50), nullable=False)  # "deploy", "rollback", "hot_swap"
    performed_by_user_id = Column(String(100), nullable=False)
    performed_by_username = Column(String(100), nullable=False)

    reason = Column(Text, nullable=True)  # 部署原因说明
    notes = Column(Text, nullable=True)  # 额外注释

    environment = Column(SQLAlchemyEnum(DeploymentEnvironment), default=DeploymentEnvironment.PRODUCTION)

    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (Index("idx_prompt_version_deployed", "prompt_name", "version_after", "environment"),)

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "id": self.id,
            "prompt_name": self.prompt_name,
            "version_before": self.version_before,
            "version_after": self.version_after,
            "action_type": self.action_type,
            "performed_by_user_id": self.performed_by_user_id,
            "performed_by_username": self.performed_by_username,
            "reason": self.reason,
            "notes": self.notes,
            "environment": (
                self.environment.value if isinstance(self.environment, DeploymentEnvironment) else self.environment
            ),
            "success": self.success,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
        }
