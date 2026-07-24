import os

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# 优先从环境变量读取 DATABASE_URL，未配置则降级使用本地 SQLite
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./quant_agent.db")

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    # SQLite 专用配置 (单文件数据库，无须复杂连接池)
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # PostgreSQL / MySQL 连接池配置（ARCH-04：参数全部 env 配置化）
    POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
    MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "40"))
    POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "10"))
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================
# 异步数据库配置 (AsyncSession) - 用于极致高并发场景
# ==========================================
# 将传统同步 URL 动态转换为异步驱动 URL (aiosqlite / asyncpg)
ASYNC_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://").replace(
    "postgresql://", "postgresql+asyncpg://"
)  # noqa: E501

if ASYNC_DATABASE_URL.startswith("sqlite"):
    async_engine = create_async_engine(ASYNC_DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # 💡 内存优化：使用与同步引擎相同的优化后配置
    async_engine = create_async_engine(
        ASYNC_DATABASE_URL,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

AsyncSessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_db():
    async with AsyncSessionLocal() as db:
        yield db
