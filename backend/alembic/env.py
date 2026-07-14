"""
Alembic 迁移环境配置（BE-07）

自动从 .env 加载 DATABASE_URL，并导入所有 SQLAlchemy 模型以支持 autogenerate。
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
load_dotenv()

# 导入所有 SQLAlchemy 模型的 Base.metadata（用于 autogenerate）
# noqa: E402 - load_dotenv() 必须在 import 之前运行
from backend.core import (  # noqa: E402
    datalake_models,  # noqa: F401
    models,  # noqa: F401
)
from backend.core.database import Base  # noqa: E402

# 导入 TickerItem 模型，确保 Alembic 可以识别并生成迁移脚本
from backend.services.ticker_service import TickerItem  # noqa: E402, F401

# Alembic Config 对象
config = context.config

# 日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 从环境变量动态注入数据库 URL（覆盖 alembic.ini 的占位值）
db_url = os.getenv("DATABASE_URL", "sqlite:///./quant_agent.db")
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在 'offline' 模式下运行迁移（仅生成 SQL，不连接数据库）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在 'online' 模式下运行迁移（实际连接数据库并执行 DDL）"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
