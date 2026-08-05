"""Futu OpenD 数据源子服务包。

从 backend.services.futu 物理迁移而来，作为主节点 data_subservice 的唯一
Futu OpenD 长连接出口。主服务不再持有任何 futu SDK 连接，仅通过 HTTP 调
用本包（source="futu"）消费 REST 数据，并通过 Redis 消费实时推送流。
"""

from .service import FutuService, futu_service

__all__ = ["futu_service", "FutuService"]
