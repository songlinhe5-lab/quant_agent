import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(unique=True, index=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column()

    # 账号安全：登录失败次数与锁定截至时间
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(default=None)

    # 关联配置表
    preferences: Mapped[Optional["UserPreference"]] = relationship(back_populates="owner", uselist=False)  # noqa: E501


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501
    ticker: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    message: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    # 以 JSON 格式存储用户自定义的 10 个指标 Symbol 列表
    macro_symbols: Mapped[List[str]] = mapped_column(JSON, default=lambda: ["SPY", "QQQ", "VIX", "TNX"])  # noqa: E501

    owner: Mapped["User"] = relationship(back_populates="preferences")


class SentimentRecord(Base):
    """市场情绪与宏观风向标历史记录表"""

    __tablename__ = "sentiment_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )  # noqa: E501
    vix_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 恐慌指数 VIX  # noqa: E501
    pc_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 期权多空比 Put/Call Ratio  # noqa: E501
    credit_spread: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 高收益债利差  # noqa: E501
    fear_greed_score: Mapped[Optional[int]] = mapped_column(nullable=True)  # 贪婪恐惧指数  # noqa: E501


class AgentSession(Base):
    """大模型 Agent 的会话持久化存储表 (冷数据落盘)"""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # 允许绑定给登录用户，实现多用户会话管理
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # noqa: E501
    title: Mapped[str] = mapped_column(String(255), default="新对话")
    messages: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # noqa: E501
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )  # noqa: E501

    owner: Mapped[Optional["User"]] = relationship("User")


class PerformanceLog(Base):
    """系统性能监控日志表 (慢请求与事件循环卡顿)"""

    __tablename__ = "performance_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )  # noqa: E501
    log_type: Mapped[str] = mapped_column(String(50), index=True)  # 'event_loop_block' 或 'slow_request'  # noqa: E501
    duration_ms: Mapped[float] = mapped_column(Float)  # 耗时或卡顿延迟 (毫秒)  # noqa: E501
    endpoint: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # 发生慢请求的 API 路径  # noqa: E501
    details: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # 附加的详情描述  # noqa: E501


class ScreenerSubscription(Base):
    """选股器定时订阅任务表"""

    __tablename__ = "screener_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    dsl: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(default=True)
    # 💡 新增：用户自定义的每日触发时间 (HH:MM 格式)
    trigger_time: Mapped[str] = mapped_column(String(5), default="18:00")
    # 💡 新增：记录上次成功触发的时间，防止重复执行
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)  # noqa: E501
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # noqa: E501

    owner: Mapped["User"] = relationship()


class WebpageKnowledgeBase(Base):
    __tablename__ = "webpage_knowledge_base"

    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    url: Mapped[str] = mapped_column(String, index=True)  # 标量：来源出处
    content: Mapped[str] = mapped_column(Text)  # 标量：网页正文碎片
    timestamp: Mapped[int] = mapped_column(Integer, index=True)  # 标量：时间戳
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, index=True, nullable=True
    )  # 标量：多租户隔离 (NULL 为系统全局公共库)  # noqa: E501

    embedding = mapped_column(Vector(EMBEDDING_DIM))  # 向量：特征表示

    __table_args__ = (
        # 建立 HNSW 高性能向量索引
        Index(
            "hnsw_idx_webpage_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={
                "m": 16,
                "ef_construction": 64,
            },  # HNSW 超参数 (平衡召回率与内存)  # noqa: E501
            postgresql_ops={"embedding": "vector_cosine_ops"},  # 指定使用余弦距离运算类  # noqa: E501
        ),
    )


class ScreenerRule(Base):
    __tablename__ = "quant_screener_rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    desc_text: Mapped[str] = mapped_column(Text)
    rule_text: Mapped[str] = mapped_column(Text)
    rule_type: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )  # 标量：用于类别过滤  # noqa: E501
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)  # 标量：多租户隔离  # noqa: E501

    embedding = mapped_column(Vector(EMBEDDING_DIM))  # 向量：特征表示

    __table_args__ = (
        # 建立 HNSW 高性能向量索引
        Index(
            "hnsw_idx_screener_rule_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class RefreshTokenBlacklist(Base):
    """刷新 Token 黑名单表"""

    __tablename__ = "refresh_token_blacklist"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)  # JWT ID
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())  # noqa: E501


class Order(Base):
    """订单记录表（模拟 + 实盘都写入）"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(4), index=True)  # 'buy' or 'sell'
    order_type: Mapped[str] = mapped_column(String(12))
    qty: Mapped[int] = mapped_column(Integer)
    filled_qty: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_fill_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), index=True)
    is_simulated: Mapped[bool] = mapped_column(default=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )  # noqa: E501


class AuditLog(Base):
    """操作审计日志表"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, default=dict)
    ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)  # noqa: E501
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501


class ClientHeartbeat(Base):
    """客户端 APM 心跳表"""

    __tablename__ = "client_heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    platform: Mapped[str] = mapped_column(String(16))  # 'ios' | 'android' | 'harmonyos'
    app_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    memory_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ws_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501

    __table_args__ = (
        Index("idx_heartbeat_platform", "platform"),
        Index("idx_heartbeat_created", "created_at"),
    )
