"""
Domain 实体聚合门面（ARCH-10 · 领域实体沉淀）

BT-01 / ALERT-03 落地后，核心领域对象已分散在：
  - backend/engine/strategy.py      → Strategy（策略抽象基类）
  - backend/engine/contracts.py     → OrderIntent / OrderUpdate（订单契约）
  - backend/core/alert_models.py    → AlertRule / AlertRuleType（告警规则）

docs/03 §2.1 明确 Domain 层目标内容为「Strategy · Order · AlertRule · Portfolio · Ports」，
其中 engine/ 属 Domain 层的引擎子集。本模块作为 Domain 层的**统一聚合门面**，
认领并 re-export 上述领域实体，使下游以语义化路径引用：

    from backend.domain.entities import Strategy, OrderIntent, AlertRule

而非散落引用 engine / core 内部路径。遵循 domain/__init__.py「避免过早复制 DTO」
的哲学：实体定义仍保留在原模块，此处仅做稳定聚合（非物理复制）。
若后续架构评审决定物理归一，可迁移定义并保留原模块 re-export 兼容层。
"""

from __future__ import annotations

from backend.core.alert_models import AlertRule, AlertRuleType
from backend.engine.contracts import OrderIntent, OrderUpdate
from backend.engine.strategy import Strategy

__all__ = ["Strategy", "OrderIntent", "OrderUpdate", "AlertRule", "AlertRuleType"]
