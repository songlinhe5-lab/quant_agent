"""
Quant Agent 主网关入口 (ARCH-01 瘦身后)
仅保留: create_app() + 路由挂载 + 静态资源
"""

import os
import socket
import sys
import warnings

# 💡 过滤 macOS/Linux 下 Uvicorn 热重载强退时的无害 POSIX 信号量泄漏警告
warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# 🚨 全局线程死锁防御：为底层所有未显式指定 timeout 的同步 Socket 注入 15 秒超时
socket.setdefaulttimeout(15.0)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

# --- 数据库初始化 (必须在所有 model 导入之后、app 创建之前) ---
from backend.core import datalake_models, models  # noqa: E402, F401
from backend.core.database import Base, engine  # noqa: E402
from backend.services.ticker_service import TickerItem  # noqa: E402, F401

try:
    from sqlalchemy import text

    with engine.begin() as conn:
        is_pg = conn.dialect.name == "postgresql"
        if is_pg:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        if is_pg:
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_symbol ON tickers USING gin (symbol gin_trgm_ops);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_name ON tickers USING gin (name gin_trgm_ops);"))
            print("✅ [System] PostgreSQL pgvector 与 pg_trgm 扩展及全局索引挂载就绪！")
except Exception as e:
    print(f"⚠️ [System] 自动创建数据库表失败 (请确认数据库服务已启动): {e}")

# --- 核心基础设施 ---
from backend.bootstrap.lifecycle import app_lifespan, global_llm_client, global_registry  # noqa: E402, F401
from backend.core.middleware import AccessLogMiddleware  # noqa: E402
from backend.core.openapi_schema import (  # noqa: E402
    API_VERSION,
    OPENAPI_DESCRIPTION,
    OPENAPI_TAGS,
    OPENAPI_TITLE,
    install_custom_openapi,
)
from backend.core.otel_config import init_otel  # noqa: E402
from backend.core.structlog_config import configure_structlog  # noqa: E402

# --- 中间件 & 异常处理 ---
from backend.core.exception_handlers import register_exception_handlers  # noqa: E402
from backend.middleware.stack import register_middleware  # noqa: E402

# --- 业务路由 ---
from backend.routers.alert import router as alert_router  # noqa: E402
from backend.routers.audit import router as audit_router  # noqa: E402
from backend.routers.auth import router as auth_router  # noqa: E402
from backend.routers.backtest import router as backtest_router  # noqa: E402
from backend.routers.backtest_reports import router as backtest_reports_router  # noqa: E402
from backend.routers.calendars import router as calendars_router  # noqa: E402
from backend.routers.chat import router as chat_router  # noqa: E402
from backend.routers.client import router as client_router  # noqa: E402
from backend.routers.data_source import router as data_source_router  # noqa: E402
from backend.routers.datalake import router as datalake_router  # noqa: E402
from backend.routers.datasource import router as datasource_rl_router  # noqa: E402
from backend.routers.earnings_router import router as earnings_router  # noqa: E402
from backend.routers.eval import router as eval_router  # noqa: E402
from backend.routers.expert_team import router as expert_team_router  # noqa: E402
from backend.routers.factor import router as factor_router  # noqa: E402
from backend.routers.alpha158 import router as alpha158_router  # noqa: E402
from backend.routers.futu_admin import router as futu_admin_router  # noqa: E402
from backend.routers.internal import router as internal_router  # noqa: E402
from backend.routers.logs import router as logs_router  # noqa: E402
from backend.routers.macro import router as macro_router  # noqa: E402
from backend.routers.market import router as market_router  # noqa: E402
from backend.routers.mcp import router as mcp_router  # noqa: E402
from backend.routers.oms import router as oms_router  # noqa: E402
from backend.routers.options import router as options_router  # noqa: E402
from backend.routers.paper import router as paper_router  # noqa: E402
from backend.routers.portfolio import router as portfolio_router  # noqa: E402
from backend.routers.preferences import router as preferences_router  # noqa: E402
from backend.routers.research import router as research_router  # noqa: E402
from backend.routers.risk import router as risk_router  # noqa: E402
from backend.routers.screener import router as screener_router  # noqa: E402
from backend.routers.search import router as search_router  # noqa: E402
from backend.routers.settings import router as settings_router  # noqa: E402
from backend.routers.strategy import router as strategy_router  # noqa: E402
from backend.routers.system import router as system_router  # noqa: E402
from backend.routers.system_health import root_router, router as system_health_router  # noqa: E402
from backend.routers.trade import router as trade_router  # noqa: E402

# ─── API 版本前缀 ─────────────────────────────────────────────
API_URL_VERSION = os.getenv("API_URL_VERSION", "v1")
API_PREFIX = f"/api/{API_URL_VERSION}"


def create_app() -> FastAPI:
    """应用工厂：组装所有组件并返回 FastAPI 实例"""
    application = FastAPI(
        title=OPENAPI_TITLE,
        description=OPENAPI_DESCRIPTION.strip(),
        version=API_VERSION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=app_lifespan,
    )
    install_custom_openapi(application)

    # 可观测性
    init_otel(application)
    configure_structlog()

    # 异常处理 & 中间件
    register_exception_handlers(application)
    register_middleware(application)

    # CORS
    allowed_origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000,https://quant-agent.pages.dev,https://quant.stephenhe.com",
    ).split(",")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    application.add_middleware(AccessLogMiddleware)

    # ─── 路由挂载 ─────────────────────────────────────────────
    # 系统基础设施 (根级: /, /monitor, /metrics, /mcp)
    application.include_router(root_router)
    application.include_router(mcp_router)

    # 系统健康检查 (API_PREFIX: /health, /cluster, /webhook)
    application.include_router(system_health_router, prefix=API_PREFIX)

    # 业务路由 (统一 API_PREFIX)
    application.include_router(chat_router, prefix=API_PREFIX)
    application.include_router(settings_router, prefix=API_PREFIX)
    application.include_router(market_router, prefix=API_PREFIX)
    application.include_router(trade_router, prefix=API_PREFIX)
    application.include_router(macro_router, prefix=API_PREFIX)
    application.include_router(calendars_router, prefix=API_PREFIX)
    application.include_router(preferences_router, prefix=API_PREFIX)
    application.include_router(auth_router, prefix=API_PREFIX)
    application.include_router(backtest_router, prefix=API_PREFIX)
    application.include_router(backtest_reports_router, prefix=API_PREFIX)
    application.include_router(datalake_router, prefix=API_PREFIX)
    application.include_router(screener_router, prefix=API_PREFIX)
    application.include_router(search_router, prefix=API_PREFIX)
    application.include_router(strategy_router, prefix=API_PREFIX)
    application.include_router(oms_router, prefix=API_PREFIX)
    application.include_router(audit_router, prefix=API_PREFIX)
    application.include_router(client_router, prefix=API_PREFIX)
    application.include_router(system_router, prefix=API_PREFIX)
    application.include_router(risk_router, prefix=API_PREFIX)
    application.include_router(paper_router, prefix=API_PREFIX)
    application.include_router(futu_admin_router, prefix=API_PREFIX)
    application.include_router(alert_router, prefix=API_PREFIX)
    application.include_router(logs_router, prefix=API_PREFIX)
    application.include_router(eval_router, prefix=API_PREFIX)
    application.include_router(earnings_router, prefix=API_PREFIX)
    application.include_router(research_router, prefix=API_PREFIX)
    application.include_router(factor_router, prefix=API_PREFIX)
    application.include_router(alpha158_router, prefix=API_PREFIX)
    application.include_router(options_router, prefix=API_PREFIX)
    application.include_router(portfolio_router, prefix=API_PREFIX)
    application.include_router(internal_router, prefix=API_PREFIX)
    application.include_router(data_source_router, prefix=API_PREFIX)
    application.include_router(datasource_rl_router, prefix=API_PREFIX)
    application.include_router(expert_team_router, prefix=API_PREFIX)

    # 静态资源 (前端编译产物)
    dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
    assets_dir = os.path.join(dist_dir, "assets")
    if os.path.exists(assets_dir):
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    return application


app = create_app()
