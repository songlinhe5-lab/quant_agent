import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import JSON, BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .database import Base

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))

# 💡 兼容处理：统一使用 TypeDecorator 封装 Vector 类型
# SQLite 降级为 LargeBinary，PostgreSQL 尝试使用 pgvector.sqlalchemy.Vector
try:
    from pgvector.sqlalchemy import Vector as _PGVector

    class Vector(_PGVector):
        """PostgreSQL pgvector 原生向量类型"""

        pass
except ImportError:
    from sqlalchemy import LargeBinary
    from sqlalchemy.types import TypeDecorator

    class Vector(TypeDecorator):
        """SQLite 兼容：用 LargeBinary 存储向量（仅测试/开发环境）"""

        impl = LargeBinary
        cache_ok = True

        def __init__(self, dim=None):
            super().__init__()
            self.dim = dim


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
    # AI-04: RAG 知识库治理 — 分类 TTL + Embedding 版本管理
    category: Mapped[Optional[str]] = mapped_column(
        String(20), index=True, nullable=True
    )  # 枚举: financial_report / news / macro / general  # noqa: E501
    embedding_model_version: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )  # 记录生成该向量的 embedding 模型版本  # noqa: E501

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
    platform: Mapped[str] = mapped_column(String(16))  # 'ios' | 'android' | 'harmonyos' | 'web'
    app_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    device_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    memory_mb: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ws_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # OBS-03: Web Vitals（可空，非 Web 端不填）
    lcp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cls: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ttfb_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501

    __table_args__ = (
        Index("idx_heartbeat_platform", "platform"),
        Index("idx_heartbeat_created", "created_at"),
    )


class NavSnapshot(Base):
    """净值快照持久化表 (分账户独立记录，用于历史净值曲线与回撤分析)"""

    __tablename__ = "nav_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    market: Mapped[str] = mapped_column(String(8), index=True)  # 'HK' | 'US'
    nav: Mapped[float] = mapped_column(Float)  # 总净值 (total_assets)
    cash: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 可用现金
    market_val: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 持仓市值
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)  # noqa: E501

    __table_args__ = (Index("idx_nav_snapshot_market_time", "market", "created_at"),)


# ─────────────────────────────────────────────────────────────
# STRAT-03a: 策略版本管理表
# ─────────────────────────────────────────────────────────────


class Strategy(Base):
    """策略主表：每个策略一条记录，指向 head_version_id"""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 策略名称作为主键
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    head_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 指向最新版本
    deployed_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 指向已部署版本
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_archived: Mapped[bool] = mapped_column(default=False)

    versions: Mapped[List["StrategyVersion"]] = relationship(back_populates="strategy", cascade="all, delete-orphan")


class StrategyVersion(Base):
    """策略版本表：每次保存创建一个新版本，不可变快照"""

    __tablename__ = "strategy_versions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UUID
    strategy_id: Mapped[str] = mapped_column(String(64), ForeignKey("strategies.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)  # 版本序号，递增
    code: Mapped[str] = mapped_column(Text)  # 完整源码
    code_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256(code)
    params_schema: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 参数 schema
    source: Mapped[str] = mapped_column(
        String(32), index=True
    )  # 'manual' | 'ai-apply' | 'auto-fix' | 'ast-fix' | 'restore'
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # 用户备注
    parent_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # 父版本 ID (用于 restore 溯源)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    strategy: Mapped["Strategy"] = relationship(back_populates="versions")

    __table_args__ = (
        # 幂等约束：同一策略下相同 hash 不重复创建
        Index("idx_strategy_version_unique_hash", "strategy_id", "code_hash", unique=True),
        Index("idx_strategy_version_seq", "strategy_id", "seq"),
    )


# ─────────────────────────────────────────────────────────────
# PT-01a: 纸面组合追踪
# ─────────────────────────────────────────────────────────────


class PaperPortfolio(Base):
    """纸面组合主档"""

    __tablename__ = "paper_portfolios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    name: Mapped[str] = mapped_column(String(64))
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    strategy_version_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    params: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True, default=dict)
    market: Mapped[str] = mapped_column(String(4))  # HK | US
    initial_capital: Mapped[float] = mapped_column(Float, default=100000.0)
    benchmark_backtest_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bot_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="running")  # running|paused|closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    fills: Mapped[List["PaperFill"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    positions: Mapped[List["PaperPosition"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    nav_daily: Mapped[List["PaperNavDaily"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class PaperFill(Base):
    """纸面成交流水（只增，账本 SSOT）"""

    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    portfolio_id: Mapped[str] = mapped_column(String(36), ForeignKey("paper_portfolios.id"), index=True)
    fill_seq: Mapped[int] = mapped_column(BigInteger)  # 组合内单调序号
    dt: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 成交时间 UTC
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))  # BUY | SELL
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float] = mapped_column(Float, default=0.0)
    intent_tag: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    portfolio: Mapped["PaperPortfolio"] = relationship(back_populates="fills")

    __table_args__ = (Index("idx_paper_fill_unique_seq", "portfolio_id", "fill_seq", unique=True),)


class PaperPosition(Base):
    """纸面持仓现状（投影，可从 fills 重放重建）"""

    __tablename__ = "paper_positions"

    portfolio_id: Mapped[str] = mapped_column(String(36), ForeignKey("paper_portfolios.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    last_fill_seq: Mapped[int] = mapped_column(BigInteger, default=0)  # 投影水位
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    portfolio: Mapped["PaperPortfolio"] = relationship(back_populates="positions")


class PaperNavDaily(Base):
    """纸面日终净值（不可变，PT-02 数据基座）"""

    __tablename__ = "paper_nav_daily"

    portfolio_id: Mapped[str] = mapped_column(String(36), ForeignKey("paper_portfolios.id"), primary_key=True)
    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[float] = mapped_column(Float)  # 现金 + Σ(持仓×收盘价)
    cash: Mapped[float] = mapped_column(Float)
    market_value: Mapped[float] = mapped_column(Float)
    daily_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stale_symbols: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    portfolio: Mapped["PaperPortfolio"] = relationship(back_populates="nav_daily")


class FrontendLog(Base):
    """前端日志表 (FE-05b: 浏览器端日志采集)"""

    __tablename__ = "frontend_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    level: Mapped[str] = mapped_column(String(16), index=True)  # DEBUG / INFO / WARN / ERROR
    message: Mapped[str] = mapped_column(String(2048))
    context: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
