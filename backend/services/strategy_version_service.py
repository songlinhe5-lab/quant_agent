"""
STRAT-03a: 策略版本管理服务
提供版本创建、查询、恢复等功能
"""

import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.models import Strategy, StrategyVersion


def compute_code_hash(code: str) -> str:
    """计算代码的 SHA256 哈希值"""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def save_version(
    db: Session,
    strategy_name: str,
    code: str,
    source: str = "manual",
    message: Optional[str] = None,
    parent_id: Optional[str] = None,
    params_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    保存策略版本
    - 同 hash 幂等：如果已存在相同 hash 的版本，直接返回
    - 创建新版本时自动递增 seq
    - 更新 strategy.head_version_id
    """
    code_hash = compute_code_hash(code)

    # 幂等检查：同策略下相同 hash 不重复创建
    existing = (
        db.query(StrategyVersion)
        .filter(
            StrategyVersion.strategy_id == strategy_name,
            StrategyVersion.code_hash == code_hash,
        )
        .first()
    )
    if existing:
        return {
            "version_id": existing.id,
            "seq": existing.seq,
            "code_hash": existing.code_hash,
            "is_new": False,
        }

    # 获取或创建 Strategy 记录
    strategy = db.query(Strategy).filter(Strategy.id == strategy_name).first()
    if not strategy:
        strategy = Strategy(id=strategy_name)
        db.add(strategy)
        db.flush()

    # 计算下一个 seq
    max_seq = (
        db.query(StrategyVersion.seq)
        .filter(StrategyVersion.strategy_id == strategy_name)
        .order_by(desc(StrategyVersion.seq))
        .first()
    )
    next_seq = (max_seq[0] + 1) if max_seq else 1

    # 创建新版本
    version_id = str(uuid.uuid4())
    version = StrategyVersion(
        id=version_id,
        strategy_id=strategy_name,
        seq=next_seq,
        code=code,
        code_hash=code_hash,
        source=source,
        message=message,
        parent_id=parent_id,
        params_schema=params_schema,
    )
    db.add(version)

    # 更新 head 指针
    strategy.head_version_id = version_id
    strategy.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(version)
    except IntegrityError:
        # 并发情况下可能触发唯一约束，回滚后返回已存在的版本
        db.rollback()
        existing = (
            db.query(StrategyVersion)
            .filter(
                StrategyVersion.strategy_id == strategy_name,
                StrategyVersion.code_hash == code_hash,
            )
            .first()
        )
        if existing:
            return {
                "version_id": existing.id,
                "seq": existing.seq,
                "code_hash": existing.code_hash,
                "is_new": False,
            }
        raise

    return {
        "version_id": version.id,
        "seq": version.seq,
        "code_hash": version.code_hash,
        "is_new": True,
    }


def get_versions(
    db: Session,
    strategy_name: str,
    limit: int = 50,
    include_code: bool = False,
) -> List[Dict[str, Any]]:
    """
    获取策略版本时间线 (seq 倒序)
    - 默认不包含 code 字段（节省带宽）
    """
    query = (
        db.query(StrategyVersion)
        .filter(StrategyVersion.strategy_id == strategy_name)
        .order_by(desc(StrategyVersion.seq))
        .limit(limit)
    )
    versions = query.all()

    result = []
    for v in versions:
        item = {
            "id": v.id,
            "seq": v.seq,
            "source": v.source,
            "message": v.message,
            "code_hash": v.code_hash[:8],  # 只显示前 8 位
            "parent_id": v.parent_id,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        if include_code:
            item["code"] = v.code
        result.append(item)

    return result


def get_version(db: Session, version_id: str) -> Optional[Dict[str, Any]]:
    """获取单个版本的完整信息（含代码）"""
    version = db.query(StrategyVersion).filter(StrategyVersion.id == version_id).first()
    if not version:
        return None

    return {
        "id": version.id,
        "strategy_id": version.strategy_id,
        "seq": version.seq,
        "code": version.code,
        "code_hash": version.code_hash,
        "source": version.source,
        "message": version.message,
        "parent_id": version.parent_id,
        "params_schema": version.params_schema,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


def restore_version(
    db: Session,
    strategy_name: str,
    version_id: str,
) -> Optional[Dict[str, Any]]:
    """
    恢复版本：以旧版本内容创建 source=restore 的新版本
    - parent_id 指向被恢复的版本
    """
    # 获取被恢复的版本
    source_version = db.query(StrategyVersion).filter(StrategyVersion.id == version_id).first()
    if not source_version:
        return None

    # 以旧版本内容创建新版本
    return save_version(
        db=db,
        strategy_name=strategy_name,
        code=source_version.code,
        source="restore",
        message=f"恢复自版本 {version_id[:8]}",
        parent_id=version_id,
        params_schema=source_version.params_schema,
    )


def import_drafts(db: Session, drafts_dir: str) -> int:
    """
    一次性将 strategies/drafts/*.py 导入为各策略 v1
    - 用于初始化迁移
    """
    import os

    if not os.path.exists(drafts_dir):
        return 0

    imported = 0
    for filename in os.listdir(drafts_dir):
        if not filename.endswith(".py"):
            continue

        strategy_name = filename[:-3]  # 去掉 .py 后缀
        filepath = os.path.join(drafts_dir, filename)

        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        # 检查是否已存在
        existing = db.query(StrategyVersion).filter(StrategyVersion.strategy_id == strategy_name).first()
        if existing:
            continue

        # 导入为 v1
        save_version(
            db=db,
            strategy_name=strategy_name,
            code=code,
            source="manual",
            message="从 drafts 目录导入",
        )
        imported += 1

    db.commit()
    return imported
