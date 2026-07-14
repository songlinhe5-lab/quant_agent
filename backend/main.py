import asyncio
import os
import sys
import warnings

# 💡 过滤 macOS/Linux 下 Uvicorn 热重载强退时，底层触发的无害 POSIX 信号量泄漏警告
warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")

import json  # noqa: E402
import secrets  # noqa: E402
import socket  # noqa: E402
import time  # noqa: E402
import uuid  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Any, Optional  # noqa: E402

import prometheus_client  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import (  # noqa: E402
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.security import (  # noqa: E402
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from fastapi.staticfiles import StaticFiles  # noqa: E402
from jose import JWTError, jwt  # noqa: E402
from pydantic import BaseModel  # noqa: E402

# --- BE-13: 统一响应封装 + 全局异常处理 ---
from backend.core.error_codes import ERROR_CODE_TO_HTTP_STATUS, ErrorCode  # noqa: E402
from backend.core.exceptions import QuantBaseException  # noqa: E402

# --- BE-10: OpenTelemetry Trace 接入 ---
from backend.core.otel_config import (  # noqa: E402
    get_current_trace_id,
    init_otel,
)

# --- BE-05: structlog 结构化日志 ---
from backend.core.structlog_config import (  # noqa: E402
    configure_structlog,
    latency_ms_var,
    new_trace_id,
    symbol_var,
    trace_id_var,
)

# 将项目根目录加入 sys.path，避免直接运行 python backend/main.py 时出现 ModuleNotFoundError: No module named 'backend'  # noqa: E501
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

# 🚨 全局线程死锁防御：为底层所有未显式指定 timeout 的同步 Socket 注入 15 秒超时。
# 系统中如 AKShare, ChromaDB 内部高度依赖 requests 且未暴露 timeout 参数。
# 若外部接口发生 TCP 假死，asyncio.to_thread 的物理线程将永久阻塞，最终彻底榨干 FastAPI 全局线程池！  # noqa: E501
# 设定全局默认超时是封堵第三方同步库“线程黑洞”的最底线安全手段。
socket.setdefaulttimeout(15.0)

# 💡 性能优化：OpenAI 和 Hermes Agent 改为延迟导入，降低启动内存
# from openai import AsyncOpenAI  # noqa: E402  # 延迟到 lifespan 中导入
# from hermes_agent.agent import HermesAgent  # noqa: E402
# from hermes_agent.tool_registry import ToolRegistry  # noqa: E402

from backend.core import (  # noqa: E402
    datalake_models,  # noqa: F401
    models,  # noqa: F401
)
from backend.core.database import AsyncSessionLocal, Base, SessionLocal, async_engine, engine  # noqa: E402
from backend.core.security import get_password_hash  # noqa: E402

# 导入 TickerItem 模型，确保数据库表被创建
# F401: 此导入看似未使用，但实际是为了让 SQLAlchemy 注册该模型，请勿删除
from backend.services.ticker_service import TickerItem  # noqa: E402, F401

# 自动创建数据库表与必要扩展
try:
    from sqlalchemy import text

    with engine.begin() as conn:
        is_pg = conn.dialect.name == "postgresql"
        if is_pg:
            # 1. 自动启用所需的所有 PG 扩展 (向量搜索 vector + 模糊搜索 pg_trgm)
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        if is_pg:
            # 2. 表创建完成后，挂载额外的 GIN 高性能索引
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_symbol ON tickers USING gin (symbol gin_trgm_ops);")
            )  # noqa: E501
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_name ON tickers USING gin (name gin_trgm_ops);")
            )  # noqa: E501
            print("✅ [System] PostgreSQL pgvector 与 pg_trgm 扩展及全局索引挂载就绪！")
except Exception as e:
    print(f"⚠️ [System] 自动创建数据库表失败 (请确认数据库服务已启动): {e}")

from backend.core.logger import logger  # noqa: E402, I001
from backend.services.market_engine import manager  # noqa: E402, I001
from backend.core.middleware import AccessLogMiddleware  # noqa: E402
from backend.core.redis_client import (  # noqa: E402
    l1_cached_redis,
    redis_batch_writer,
    redis_client,
)
from backend.routers.alert import router as alert_router  # noqa: E402
from backend.routers.audit import router as audit_router  # noqa: E402
from backend.routers.auth import router as auth_router  # noqa: E402
from backend.routers.backtest import router as backtest_router  # noqa: E402
from backend.routers.logs import router as logs_router  # noqa: E402
from backend.routers.backtest_reports import router as backtest_reports_router  # noqa: E402
from backend.routers.datalake import router as datalake_router  # noqa: E402
from backend.routers.client import (  # noqa: E402
    router as client_router,  # BE-08: 客户端 APM 心跳
)
from backend.routers.internal import router as internal_router  # noqa: E402
from backend.routers.macro import router as macro_router  # noqa: E402

# --- 业务模块路由 ---
from backend.routers.futu_admin import router as futu_admin_router  # noqa: E402
from backend.routers.market import router as market_router  # noqa: E402
from backend.routers.oms import router as oms_router  # noqa: E402
from backend.routers.preferences import router as preferences_router  # noqa: E402
from backend.routers.risk import router as risk_router  # noqa: E402
from backend.routers.screener import router as screener_router  # noqa: E402
from backend.routers.search import router as search_router  # noqa: E402
from backend.routers.strategy import router as strategy_router  # noqa: E402
from backend.routers.paper import router as paper_router  # noqa: E402, PT-01b
from backend.routers.system import router as system_router  # noqa: E402
from backend.routers.trade import router as trade_router  # noqa: E402
from backend.routers.data_source import router as data_source_router  # noqa: E402
from backend.routers.datasource import router as datasource_rl_router  # noqa: E402
from backend.routers.eval import router as eval_router  # noqa: E402, AI-03 eval
from backend.routers.research import router as research_router  # noqa: E402, AI-01 研报
from backend.routers.factor import router as factor_router  # noqa: E402, AI-02 因子挖掘
from backend.routers.alpha158 import router as alpha158_router  # noqa: E402, AI-03 因子库
from backend.routers.options import router as options_router  # noqa: E402, TRADE-01 期权筛选
from backend.routers.portfolio import router as portfolio_router  # noqa: E402, TRADE-03 组合优化
from backend.services.fred_service import fred_service  # noqa: E402
from backend.services.futu_service import futu_service  # noqa: E402
from backend.services.llm_service import llm_service  # noqa: E402
from backend.services.notification_service import notification_service  # noqa: E402
from backend.services.system_monitor_service import system_monitor_service  # noqa: E402
from backend.services.yfinance_service import yf_service  # noqa: E402

# --- 全局单例与连接池 ---
global_registry = None
global_llm_client = None

# 引入自检脚本中的深度测试方法（可选，仅本地开发时可用）
try:
    from scripts.test_all_services import (  # noqa: E402
        test_fred_service,
        test_futu_service,
        test_notification_service,
    )
except ImportError:
    # 生产环境 Docker 镜像中不包含 scripts/ 目录，跳过自检
    test_fred_service = None
    test_futu_service = None
    test_notification_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore
    """系统的全局生命周期管理器 (替代废弃的 on_event 钩子)"""
    global global_registry, global_llm_client

    # === 启动阶段 (Startup) ===
    print("\n🚀 [Startup] 正在执行后端核心服务深度自检...")

    # 💡 性能安全防御：全局限制 asyncio 与 AnyIO 的最大物理线程池容量，防止 OOM
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
        # 限制 asyncio.to_thread() 的默认线程池大小，防止外部接口卡死时物理线程无限飙升耗尽内存  # noqa: E501
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="GlobalAsyncioWorker")
        loop.set_default_executor(executor)

        # 同时限制 FastAPI (AnyIO) 底层同步路由/依赖函数的最大并发 Worker 数
        from anyio.to_thread import current_default_thread_limiter

        limiter = current_default_thread_limiter()
        limiter.total_tokens = 64
        print("✅ [System] 全局物理线程池容量已安全限制为最大 64 个。")
    except Exception as e:
        print(f"⚠️ [System] 配置全局线程池失败: {e}")

    # 0. 初始化默认系统管理员账号
    print("🚀 [Startup] 正在初始化系统默认账号...")
    try:
        with SessionLocal() as db:
            admin = db.query(models.User).filter(models.User.username == "admin").first()  # noqa: E501
            if not admin:
                admin_user = models.User(
                    username="admin",
                    email="admin@quant.local",
                    hashed_password=get_password_hash("admin"),  # noqa: F821
                )
                db.add(admin_user)
                db.commit()
                print("✅ [Startup] 默认管理员账号 (admin/admin) 初始化成功！")
    except Exception as e:
        print(f"⚠️ [Startup] 管理员账号初始化失败: {e}")

    # 1. 运行雅虎财经测试 (防限流：开发期间若经常 reload，可在环境配置中加上 SKIP_YF_TEST=1 跳过)  # noqa: E501
    # if os.getenv("SKIP_YF_TEST") != "1":
    #     await test_yfinance_service()

    # 💡 增加容灾包裹：防止外部 API 或富途网关不通导致整个 Docker 容器死循环无法启动
    # 🚨 关键修复：为每个预检添加超时，防止单个服务卡住阻塞整个 API 启动
    try:
        # 2. 连接 Futu OpenD (生产环境必须连接，不依赖 scripts/ 目录)
        # 💡 关键：在调用 to_thread 前先注册主事件循环，供推送回调跨线程桥接使用
        from backend.services.futu import push_handler

        push_handler.set_main_loop(asyncio.get_running_loop())
        await asyncio.wait_for(asyncio.to_thread(futu_service.connect), timeout=15.0)
        print(f"✅ [Startup] Futu OpenD 连接状态: {futu_service.status}")
    except asyncio.TimeoutError:
        print("⚠️ [Startup] 富途 OpenD 连接超时 (15s)，已自动降级跳过")
    except Exception as e:
        print(f"⚠️ [Startup] 富途 OpenD 连接失败，已自动降级跳过: {e}")

    try:
        # 3. 运行 Redis 连通性与系统通知测试
        if test_notification_service is not None:
            await asyncio.wait_for(test_notification_service(), timeout=10.0)  # type: ignore
        # 4. 运行 FRED 宏观数据接口测试
        if test_fred_service is not None:
            await asyncio.wait_for(test_fred_service(), timeout=10.0)  # type: ignore
    except asyncio.TimeoutError:
        print("⚠️ [Startup] 核心外部服务预检超时 (10s)，已自动降级跳过")
    except Exception as e:
        print(f"⚠️ [Startup] 核心外部服务连通性预检失败: {e}")

    print("\n🎉 [Startup] 所有后端服务自检完成，API 网关启动就绪！\n")

    # 🧠 [Agent] 初始化 AI 主脑相关服务
    # 💡 性能优化：延迟导入重量级依赖，降低启动内存
    print("🛠️  [Agent Startup] 装载量化 Tools 沙箱网络客户端...")
    from hermes_agent.tool_registry import ToolRegistry

    global_registry = ToolRegistry()
    print(f"✅ [Agent Startup] 成功挂载 {len(global_registry.tools)} 个 AI Agent 核心工具！")  # noqa: E501

    print("🔌 [Agent Startup] 初始化全局共享的大模型连接池...")
    from openai import AsyncOpenAI

    llm_api_key = os.getenv("LLM_API_KEY", "")
    if llm_api_key:
        global_llm_client = AsyncOpenAI(
            api_key=llm_api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        )
        print("✅ [Agent Startup] LLM 连接池已初始化")
    else:
        global_llm_client = None
        print("⚠️ [Agent Startup] LLM_API_KEY 未配置，跳过 LLM 客户端初始化")

    # 🚀 启动事件循环健康监控探针
    loop_monitor_task = asyncio.create_task(system_monitor_service.event_loop_monitor_daemon())  # noqa: E501

    await manager.start_background_tasks()  # type: ignore

    asyncio.create_task(notification_service.send_alert("✅ [Quant Agent] 量化引擎数据网关已成功连接并启动！"))  # noqa: E501

    # 🚀 启动 NAV 快照守护进程 (每 5 分钟分账户记录 HK/US 净值到 Redis + DB)
    async def _nav_snapshot_daemon():
        """每 5 分钟分账户记录 NAV 快照到 Redis List + 持久化到数据库"""
        while True:
            try:
                # 并发获取 HK + US 账户
                hk_acc, us_acc = await asyncio.gather(
                    futu_service.get_account_info("HK"),
                    futu_service.get_account_info("US"),
                    return_exceptions=True,
                )
                for market, acc in [("HK", hk_acc), ("US", us_acc)]:
                    if isinstance(acc, dict) and acc.get("status") == "success":
                        nav = float(acc.get("total_assets", 0))
                        cash = float(acc.get("cash", 0))
                        market_val = float(acc.get("market_val", 0))
                        if nav > 0:
                            # 1. 写入 Redis (最近 24h 快速查询)
                            key = f"quant:risk:nav_snapshots:{market}"
                            await redis_client.lpush(key, json.dumps({"ts": time.time(), "nav": nav}))
                            await redis_client.ltrim(key, 0, 287)

                            # 2. 持久化到数据库 (长期历史存储)
                            try:
                                async with AsyncSessionLocal() as db:
                                    snapshot = models.NavSnapshot(
                                        market=market,
                                        nav=nav,
                                        cash=cash,
                                        market_val=market_val,
                                    )
                                    db.add(snapshot)
                                    await db.commit()
                            except Exception as db_err:
                                logger.warning(f"[NAV Daemon] DB 写入失败 ({market}): {db_err}")
            except Exception as e:
                logger.warning(f"[NAV Daemon] 快照记录失败: {e}")
            await asyncio.sleep(300)  # 5 分钟

    nav_snapshot_task = asyncio.create_task(_nav_snapshot_daemon())
    print("✅ [Startup] NAV 快照守护进程已启动 (每 5 分钟)")

    # 🚀 OMS-04: 启动持仓实时同步守护进程 (每 30 秒从 Futu 拉取真实持仓写入 Redis)
    async def _oms_position_sync_daemon():
        """每 30 秒从 Futu 拉取 HK/US 真实持仓列表，写入 Redis 缓存"""
        from backend.services.oms_service import oms_service

        while True:
            try:
                await asyncio.gather(
                    oms_service.sync_positions_from_futu("HK"),
                    oms_service.sync_positions_from_futu("US"),
                    return_exceptions=True,
                )
            except Exception as e:
                logger.warning(f"[OMS Position Daemon] 同步失败: {e}")
            await asyncio.sleep(30)  # 30 秒

    oms_position_task = asyncio.create_task(_oms_position_sync_daemon())
    print("✅ [Startup] OMS 持仓同步守护进程已启动 (每 30 秒)")

    # 🚀 OMS-05: 启动 BotRuntimeManager — 恢复之前运行的 Bot 算力节点
    from backend.services.bot_runtime import bot_runtime

    try:
        restored = await bot_runtime.restore_bots_from_redis()
        print(f"✅ [Startup] BotRuntimeManager 已启动 (恢复 {restored} 个 Bot)")
    except Exception as e:
        logger.warning(f"[Startup] BotRuntimeManager 恢复失败: {e}")

    # 🚀 OMS-08: 启动 AlgoEngine — 恢复之前运行中的算法拆单
    from backend.services.algo_engine import algo_engine

    try:
        algo_restored = await algo_engine.restore_from_redis()
        print(f"✅ [Startup] AlgoEngine 已启动 (恢复 {algo_restored} 个算法订单)")
    except Exception as e:
        logger.warning(f"[Startup] AlgoEngine 恢复失败: {e}")

    # 🚀 MARKET-01: 启动 broadcast_loop — 应用启动即运行，无需等待 WebSocket 连接
    try:
        await manager.start_background_tasks()
        print("✅ [Startup] MarketEngine broadcast_loop 已启动")
    except Exception as e:
        logger.warning(f"[Startup] MarketEngine 启动失败: {e}")

    yield  # 挂起，此时 FastAPI 正式对外提供 HTTP 与 WS 服务

    # === 销毁阶段 (Shutdown) ===
    print("🛑 正在关闭后端服务，释放资源...")

    try:
        tasks_to_await = []

        # 停止 NAV 快照守护进程
        if "nav_snapshot_task" in locals() and not nav_snapshot_task.done():
            nav_snapshot_task.cancel()
            tasks_to_await.append(nav_snapshot_task)

        # 停止 OMS 持仓同步守护进程
        if "oms_position_task" in locals() and not oms_position_task.done():
            oms_position_task.cancel()
            tasks_to_await.append(oms_position_task)

        # OMS-05: 优雅关停所有 Bot 算力节点
        try:
            from backend.services.bot_runtime import bot_runtime

            await bot_runtime.shutdown()
        except Exception:
            pass

        # OMS-08: 优雅关停所有算法拆单
        try:
            from backend.services.algo_engine import algo_engine

            await algo_engine.shutdown()
        except Exception:
            pass

        if "loop_monitor_task" in locals() and not loop_monitor_task.done():
            loop_monitor_task.cancel()
            tasks_to_await.append(loop_monitor_task)

        # 💡 必须在关闭 Redis 之前先将依赖 Redis 的队列流推送任务终止！
        push_t = manager.push_task
        if push_t and not push_t.done():
            push_t.cancel()
            tasks_to_await.append(push_t)

        pubsub_t = getattr(manager, "pubsub_task", None)
        if pubsub_t and not pubsub_t.done():
            pubsub_t.cancel()
            tasks_to_await.append(pubsub_t)

        # 💡 等待所有后台任务完成优雅的取消过程 (给予 WebSocket 发送正常断开握手的时间)
        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
    except Exception as e:
        print(f"⚠️ 取消后台任务时发生异常: {e}")

    try:
        # 🛑 优雅释放我们在 Startup 阶段分配的全局物理线程池
        loop = asyncio.get_running_loop()
        executor = getattr(loop, "_default_executor", None)
        if executor:
            executor.shutdown(wait=False)
    except Exception:
        pass

    try:
        # 🧠 [Agent] 关闭 AI 主脑连接
        if global_llm_client:
            await global_llm_client.close()  # type: ignore

        # 释放系统 LLM 服务的共享 HTTP 客户端
        await llm_service.close()
    except Exception as e:
        print(f"⚠️ 关闭 AI 客户端异常: {e}")

    try:
        print("🛑 [Cleanup] 正在排空并关闭 Redis 异步写入队列...")
        await redis_batch_writer.stop()
    except Exception as e:
        print(f"⚠️ 关闭 Redis 队列异常: {e}")

    try:
        # 清除 Redis 临时行情缓存，避免下次启动读取到过期的脏数据
        print("🧹 [Cleanup] 正在清空 Redis 临时行情缓存...")
        await redis_client.delete("quant:quotes:latest")
    except Exception as e:
        print(f"⚠️ 清理 Redis 缓存异常: {e}")

    try:
        await redis_client.aclose()  # type: ignore
    except Exception as e:
        print(f"⚠️ 关闭 Redis 连接池异常: {e}")

    try:
        # 释放独立服务资源
        futu_service.close()
        yf_service.close()
    except Exception as e:
        print(f"⚠️ 关闭数据源资源异常: {e}")

    try:
        print("🛑 [Cleanup] 正在关闭外部 API 长连接...")
        await fred_service.close()
    except Exception as e:
        print(f"⚠️ 关闭 FRED 等 HTTP 连接池异常: {e}")

    try:
        print("🛑 [Cleanup] 正在关闭数据库连接池...")
        engine.dispose()
        await async_engine.dispose()
    except Exception as e:
        print(f"⚠️ 关闭数据库连接池异常: {e}")


from backend.core.openapi_schema import (  # noqa: E402
    API_VERSION,
    OPENAPI_DESCRIPTION,
    OPENAPI_TAGS,
    OPENAPI_TITLE,
    install_custom_openapi,
)

app = FastAPI(
    title=OPENAPI_TITLE,
    description=OPENAPI_DESCRIPTION.strip(),
    version=API_VERSION,
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
install_custom_openapi(app)

# ==========================================
# --- BE-10: OpenTelemetry Trace 初始化 ---
# ==========================================
init_otel(app)

# ==========================================
# --- BE-05: structlog 结构化日志初始化 ---
# ==========================================
configure_structlog()

# ==========================================
# --- BE-13: 全局异常处理器 ---
# ==========================================


@app.exception_handler(QuantBaseException)
async def quant_exception_handler(request: Request, exc: QuantBaseException):
    """捕获所有 QuantBaseException 子类，统一转换为 {code, msg, data, ts} 格式"""
    http_status = ERROR_CODE_TO_HTTP_STATUS.get(exc.code, 500)
    body = {
        "code": exc.code,
        "msg": exc.msg,
        "data": exc.data,
        "ts": int(time.time() * 1000),
    }
    if exc.trace_id:
        body["trace_id"] = exc.trace_id
    return JSONResponse(status_code=http_status, content=body)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """捕获 FastAPI 原生的 HTTPException，统一转换为 {code, msg, data, ts} 格式"""
    # 使用 HTTP 状态码作为业务错误码（保持与测试期望一致）
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "msg": exc.detail,
            "data": None,
            "ts": int(time.time() * 1000),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """捕获 Pydantic 请求参数校验失败，转换为 code=2001 的统一格式"""
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err["loc"]) if err.get("loc") else ""  # noqa: E741
        errors.append({"field": loc, "msg": err.get("msg", ""), "type": err.get("type", "")})  # noqa: E501
    body = {
        "code": int(ErrorCode.VALIDATION_FAILED),
        "msg": f"请求参数校验失败: {exc.errors()[0]['msg']}" if exc.errors() else "请求参数校验失败",  # noqa: E501
        "data": errors,
        "ts": int(time.time() * 1000),
    }
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局兜底异常处理器：捕获所有未预料的异常，返回 code=5000"""
    # 生成 trace_id 便于排查日志
    trace_id = str(uuid.uuid4())[:16]
    logger.error(
        f"[UnhandledException] {request.method} {request.url.path} trace_id={trace_id} error={exc}",
        exc_info=True,
    )  # noqa: E501
    body = {
        "code": int(ErrorCode.INTERNAL_ERROR),
        "msg": f"内部服务器错误 (trace_id: {trace_id})",
        "data": None,
        "ts": int(time.time() * 1000),
        "trace_id": trace_id,
    }
    return JSONResponse(status_code=500, content=body)


# ==========================================
# --- BE-13: 响应格式转换中间件 ---
# ==========================================
# 将尚未迁移的旧路由响应（不含 code 字段）自动包装为 {code, msg, data, ts} 统一格式。
# 已使用 success()/error() 的新路由不受影响（检测到 code 字段即放行）。

_SKIP_TRANSFORM_PREFIXES = (
    "/api/v1/chat",  # SSE 流式响应
    "/api/v1/sse",  # SSE 端点
    "/api/v1/ws",  # WebSocket
    "/ws/",  # WebSocket
    "/assets",  # 静态资源
    "/metrics",  # Prometheus（非 JSON）
    "/mcp",  # MCP 探针
)


@app.middleware("http")
async def response_envelope_middleware(request: Request, call_next):
    """
    BE-13: 将旧式 JSON 响应自动包装为统一信封格式。
    - StreamingResponse / FileResponse: 直接放行
    - 已有 code 字段: 直接放行（已迁移的新路由）
    - 其他 JSON: 将原 body 包入 data 字段
    """
    response = await call_next(request)
    path = request.url.path

    # 快速跳过不需要转换的路径
    if any(path.startswith(p) for p in _SKIP_TRANSFORM_PREFIXES):
        return response
    if path in ("/", "/monitor", "/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/openapi.yaml"):
        return response

    # 仅转换 JSON 响应
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response

    # 读取响应体
    try:
        body_chunks = []
        async for chunk in response.body_iterator:
            if isinstance(chunk, bytes):
                body_chunks.append(chunk)
            else:
                body_chunks.append(chunk.encode("utf-8"))
        raw_body = b"".join(body_chunks)
        data = json.loads(raw_body)
    except Exception:
        # 无法解析的响应体直接原样返回
        return JSONResponse(
            status_code=response.status_code,
            content=json.loads(raw_body) if raw_body else None,
            headers=dict(response.headers),
        )

    # 已包含统一 code 字段 → 直接放行（已迁移的路由）
    if isinstance(data, dict) and "code" in data:
        return JSONResponse(status_code=response.status_code, content=data)

    # 包装旧式响应
    envelope = {
        "code": 0 if 200 <= response.status_code < 300 else int(ErrorCode.INTERNAL_ERROR),  # noqa: E501
        "msg": "ok"
        if 200 <= response.status_code < 300
        else (data.get("message", "error") if isinstance(data, dict) else "error"),  # noqa: E501
        "data": data,
        "ts": int(time.time() * 1000),
    }
    return JSONResponse(status_code=response.status_code, content=envelope)


# ==========================================
# --- Prometheus 监控指标暴露 ---
# ==========================================
metrics_security = HTTPBasic()


def verify_metrics_auth(credentials: HTTPBasicCredentials = Depends(metrics_security)):
    # 可在 .env 中配置 METRICS_USER 和 METRICS_PASS，缺省均为 admin
    # 💡 增加 .encode("utf-8") 防御：防止输入带有非 ASCII 字符导致 secrets.compare_digest 触发 TypeError 崩溃  # noqa: E501
    current_user_bytes = credentials.username.encode("utf-8")
    current_pass_bytes = credentials.password.encode("utf-8")
    env_user_bytes = os.getenv("METRICS_USER", "admin").encode("utf-8")
    env_pass_bytes = os.getenv("METRICS_PASS", "admin").encode("utf-8")

    correct_username = secrets.compare_digest(current_user_bytes, env_user_bytes)
    correct_password = secrets.compare_digest(current_pass_bytes, env_pass_bytes)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized metrics access",
            headers={"WWW-Authenticate": "Basic"},  # noqa: E501
        )
    return credentials.username


@app.get("/metrics", include_in_schema=False)
def metrics(username: str = Depends(verify_metrics_auth)):
    # 💡 性能修复：因为 generate_latest 是同步阻塞操作，移除 async 使其运行在线程池中，防止阻塞网关的高频事件循环  # noqa: E501
    return Response(
        content=prometheus_client.generate_latest(),
        media_type=prometheus_client.CONTENT_TYPE_LATEST,
    )  # noqa: E501


# ==========================================
# 全局 API 限流中间件 (Rate Limiter)
# ==========================================
# 开发环境放宽限制，避免前端热重载/轮询触发 429
_is_dev = os.getenv("QUANT_ENV", "production") == "development"
RATE_LIMIT = 1000 if _is_dev else 100  # 开发环境 1000 次/窗口，生产环境 100 次/窗口
RATE_WINDOW = 60  # 时间窗口 (秒)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """
    BE-05 + BE-10: 为每个请求注入 trace_id 上下文。
    - OTEL 启用时：使用标准 OTEL trace_id (32-char hex)
    - 支持 W3C Trace Context 透传（上游网关注入的 traceparent header）
    - 同时在响应头中回传 X-Trace-Id，便于前端排查问题
    """
    # 尝试获取 OTEL 标准 trace_id（OTEL 中间件在更外层，span 已创建）
    otel_tid = get_current_trace_id()

    # 备用：从请求头读取或生成自定义 ID
    if not otel_tid:
        otel_tid = request.headers.get("x-trace-id", new_trace_id())

    # 注入到 structlog context var（供日志自动携带）
    token_trace = trace_id_var.set(otel_tid)
    token_symbol = symbol_var.set("-")
    token_latency = latency_ms_var.set(0.0)

    try:
        response = await call_next(request)
        # 再次尝试获取（防止 OTEL 在 call_next 过程中创建了新 span）
        otel_tid = get_current_trace_id() or otel_tid
        response.headers["X-Trace-Id"] = otel_tid
        return response
    finally:
        trace_id_var.reset(token_trace)
        symbol_var.reset(token_symbol)
        latency_ms_var.reset(token_latency)


@app.middleware("http")
async def pyinstrument_profiler_middleware(request: Request, call_next):
    """
    优雅的 pyinstrument 性能分析中间件
    使用方法: 在任意 GET/POST 接口后加上 ?profile=true
    将直接在浏览器中返回直观的交互式函数调用树 HTML 报告，彻底取代难用的 cProfile。
    """
    if request.query_params.get("profile") == "true":
        try:
            from fastapi.responses import HTMLResponse
            from pyinstrument import Profiler

            # async_mode="enabled" 完美支持 FastAPI 的 await 挂起分析
            profiler = Profiler(interval=0.001, async_mode="enabled")
            profiler.start()

            await call_next(request)

            profiler.stop()
            return HTMLResponse(content=profiler.output_html(), status_code=200)
        except ImportError:
            print("⚠️ [Profiler] 未安装 pyinstrument，请先执行 pip install pyinstrument")
            return await call_next(request)

    return await call_next(request)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # 仅拦截业务接口，放行静态资源和内部健康检查
    if not request.url.path.startswith("/assets") and request.url.path not in [
        "/",
        "/monitor",
        "/health",
    ]:  # noqa: E501
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"

        try:
            # 使用 Redis Pipeline 保证高频操作的原子性与极致性能
            async with redis_client.pipeline() as pipe:
                await pipe.incr(key)
                await pipe.expire(key, RATE_WINDOW, nx=True)  # 仅在键刚创建时设置过期时间 (需 Redis 7.0+)  # noqa: E501
                results = await pipe.execute()

            current_requests = results[0]
            if current_requests > RATE_LIMIT:
                return JSONResponse(
                    status_code=429,
                    content={
                        "status": "error",
                        "message": f"请求过于频繁，限制为 {RATE_LIMIT}次/{RATE_WINDOW}秒。",
                    },  # noqa: E501
                )
        except Exception as e:
            print(f"⚠️ [Rate Limiter] Redis 限流器异常: {e}")
            # 容灾兜底：如果 Redis 意外宕机，则自动放行所有请求，避免阻断正常业务
            pass

    return await call_next(request)


@app.middleware("http")
async def slow_request_middleware(request: Request, call_next):
    """监控慢请求的中间件，辅助定位导致阻塞的案发现场"""
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    if process_time > 1.5 and not request.url.path.startswith("/api/chat"):  # 过滤掉原本就耗时的 AI 对话  # noqa: E501
        print(f"🐢 [Slow Request] {request.method} {request.url.path} 耗时: {process_time:.2f}s")  # noqa: E501
        asyncio.create_task(
            asyncio.to_thread(
                system_monitor_service._save_performance_log,
                "slow_request",
                process_time * 1000,
                f"{request.method} {request.url.path}",
            )
        )
    return response


# 允许 Vite 等前端本地代理发起请求（SEC-11：CORS 白名单配置，禁止 *）
# 生产环境应在 .env 中配置 ALLOWED_ORIGINS 环境变量，多个域名用逗号分隔
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000,https://quant-agent.pages.dev,https://quant.stephenhe.com",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# 挂载全局请求访问与 Prometheus 性能监控中间件
app.add_middleware(AccessLogMiddleware)

# 挂载所有重构至 routers 目录下的纯净业务路由（添加 /api/v1/ 版本前缀，符合 SEC-01 安全规范）  # noqa: E501
app.include_router(market_router, prefix="/api/v1")
app.include_router(trade_router, prefix="/api/v1")
app.include_router(macro_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(backtest_reports_router, prefix="/api/v1")  # BT-02 报告持久化
app.include_router(datalake_router, prefix="/api/v1")  # DQ-03e 数据湖快照
app.include_router(screener_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(strategy_router, prefix="/api/v1")
app.include_router(oms_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(client_router, prefix="/api/v1")  # BE-08
app.include_router(system_router, prefix="/api/v1")  # System APM
app.include_router(risk_router, prefix="/api/v1")  # Risk 风控面板
app.include_router(paper_router, prefix="/api/v1")  # PT-01b 纸面组合
app.include_router(futu_admin_router)  # Futu 数据源管理 (prefix 已含 /api/v1/futu)
app.include_router(alert_router)  # ALERT-02: 告警中心 (prefix 已含 /api/v1/alert)
app.include_router(logs_router, prefix="/api/v1")  # FE-05b: 前端日志采集
app.include_router(eval_router, prefix="/api/v1")  # AI-03: Eval 评估框架
app.include_router(research_router, prefix="/api/v1")  # AI-01: 深度研报
app.include_router(factor_router, prefix="/api/v1")  # AI-02: 因子挖掘
app.include_router(alpha158_router, prefix="/api/v1")  # AI-03: Alpha158 因子库
app.include_router(options_router, prefix="/api/v1")  # TRADE-01: 期权筛选
app.include_router(portfolio_router, prefix="/api/v1")  # TRADE-03: 组合优化

# 挂载内部 API 路由（需要 HMAC 签名验证，符合 SEC-03 安全规范）
app.include_router(internal_router, prefix="/api/v1")

# 挂载数据源代理路由（支持跨节点数据源调用）
app.include_router(data_source_router, prefix="/api/v1")

# 挂载数据源限流查询路由 (RL-06)
app.include_router(datasource_rl_router, prefix="/api/v1")

# ==========================================
# --- JWT 鉴权依赖 (SSR & Client 兼容) ---
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    refresh_token: Optional[str] = Cookie(None),
):
    """从 Header (Bearer) 或 Cookie (SSR) 中提取并验证 JWT Token"""
    token = credentials.credentials if credentials else refresh_token
    if token == "null":  # 处理前端在 Token 未就绪时发来的 "null" 字符串
        token = refresh_token
    if not token:
        raise HTTPException(status_code=401, detail="请求未携带合法 Token，拒绝访问")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Token 载荷非法 (缺失 sub)")  # noqa: E501, E701
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")


def _read_file_sync(target_file: str, ext: str) -> str:
    content = ""
    if ext in [".txt", ".md", ".csv"]:
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
    elif ext == ".pdf":
        import pdfplumber

        pages_content = []
        with pdfplumber.open(target_file) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                tables = page.extract_tables()
                if tables:
                    page_text += "\n\n[本页表格数据]:\n"
                    for table in tables:
                        for row in table:
                            clean_row = [str(cell).replace("\n", " ").strip() if cell else "" for cell in row]  # noqa: E501
                            page_text += " | ".join(clean_row) + "\n"
                        page_text += "\n"
                if page_text.strip():
                    pages_content.append(page_text)
        content = "\n".join(pages_content)
    return content


@app.get("/api/v1/financial-report")
async def get_financial_report(ticker: str, chunk_index: int = 0):
    import glob
    import re

    if not ticker:
        raise HTTPException(status_code=400, detail="缺失股票代码参数")

    # 💡 边界防御：防范目录穿越攻击 (Directory / Path Traversal)
    # 严格过滤掉斜杠和反斜杠，并消除可能存在的 .. 序列，防止黑客通过构造如 ../../../.env 的 Ticker 来读取系统机密文件  # noqa: E501
    safe_ticker = re.sub(r"[^A-Z0-9_.-]", "", ticker.upper()).replace("..", "")
    if not safe_ticker:
        raise HTTPException(status_code=400, detail="非法的股票代码参数")

    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports"))  # noqa: E501
    os.makedirs(reports_dir, exist_ok=True)
    search_pattern = os.path.join(reports_dir, f"*{safe_ticker}*.*")
    matched_files = glob.glob(search_pattern)

    if not matched_files:
        return {
            "status": "error",
            "message": f"未在财报目录下找到包含 {safe_ticker} 的财报文件。",
        }  # noqa: E501

    target_file = matched_files[0]
    ext = os.path.splitext(target_file)[1].lower()

    try:
        if ext not in [".txt", ".md", ".csv", ".pdf"]:
            return {"status": "error", "message": f"不支持的文件格式: {ext}。"}
        content = await asyncio.to_thread(_read_file_sync, target_file, ext)
        max_chars = 15000
        chunks = [content[i : i + max_chars] for i in range(0, len(content), max_chars)]
        if not chunks:
            return {"status": "error", "message": "文件内容提取为空。"}
        if chunk_index < 0 or chunk_index >= len(chunks):
            return {
                "status": "error",
                "message": f"chunk_index 越界。有效范围: 0 到 {len(chunks) - 1}",
            }  # noqa: E501

        return {
            "status": "success",
            "file_path": target_file,
            "total_chunks": len(chunks),
            "current_chunk_index": chunk_index,
            "content": chunks[chunk_index],
            "message": f"成功读取财报文件第 {chunk_index + 1}/{len(chunks)} 部分。",
        }  # noqa: E501
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class YFinanceToggle(BaseModel):
    enabled: bool


@app.post("/api/v1/settings/yfinance")
async def toggle_yfinance(payload: YFinanceToggle):
    """前端一键控制 YFinance 兜底开关"""
    await l1_cached_redis.set("quant:settings:yfinance_enabled", "1" if payload.enabled else "0")  # noqa: E501
    return {
        "status": "success",
        "message": f"YFinance 兜底已{'开启' if payload.enabled else '关闭'}",
    }  # noqa: E501


@app.get("/api/v1/settings/yfinance")
async def get_yfinance_setting():
    """获取 YFinance 当前开关状态"""
    val = await l1_cached_redis.get("quant:settings:yfinance_enabled")
    return {"status": "success", "enabled": val != "0"}


@app.get("/api/v1/health")
async def health_check():
    """系统健康检查接口 (供 Docker 或 K8s Liveness Probe 使用)"""
    components = {}
    status_code = 200
    overall_status = "healthy"

    # 1. 检查 Redis 连接 (核心依赖，失败则抛出 503 触发 Docker 重启)
    try:
        await redis_client.ping()
        components["redis"] = "connected"
    except Exception as e:
        components["redis"] = f"disconnected ({e})"
        overall_status = "unhealthy"
        status_code = 503

    # 2. Futu OpenD 可能在远程 VPS 上运行，Master 不一定有本地 OpenD 实例
    #    不在此检测 futu_service.status，避免触发后台线程阻塞事件循环
    components["futu"] = "skipped (may run on remote slave nodes)"

    # 3. YFinance 属于外部高频受限 API，防止 Docker 轮询导致 IP 被封，做跳过处理
    components["yfinance"] = "skipped (prevent rate limits)"

    # 4. 监控 asyncio 默认线程池状态 (供 asyncio.to_thread 手动派发的任务使用)
    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None and hasattr(executor, "_max_workers"):
        components["asyncio_thread_pool"] = {
            "max_workers": executor._max_workers,  # 线程池最大容量
            "spawned_threads": len(executor._threads),  # 当前已孵化的真实物理线程数
            "pending_tasks": executor._work_queue.qsize(),  # 正在排队等待空闲线程的任务数
        }
    else:
        components["asyncio_thread_pool"] = "idle (lazy initialized)"

    # 5. 监控 FastAPI/AnyIO 底层线程池状态 (供同步 def 路由使用)
    try:
        from anyio.to_thread import current_default_thread_limiter

        limiter = current_default_thread_limiter()
        components["fastapi_thread_pool"] = {
            "max_workers": limiter.total_tokens,  # 允许并发执行的最大请求数 (默认40)  # noqa: E501
            "idle_workers": limiter.available_tokens,  # 当前空闲可用的 Worker 数量
            "busy_workers": limiter.total_tokens - limiter.available_tokens,
        }
    except Exception as e:
        components["fastapi_thread_pool"] = f"unknown ({e})"

    response_data = {"status": overall_status, "components": components}
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=response_data)
    return response_data


@app.get("/api/v1/cluster")
async def cluster_status():
    """节点状态概览"""
    from backend.workers.collector_registry import get_enabled_collectors

    return {
        "mode": "standalone",
        "collectors": get_enabled_collectors(),
    }


@app.get("/mcp")
async def mcp_health_check(session_id: Optional[str] = None):
    """兼容 Uptime Kuma 等监控工具针对 MCP 探针的健康检查接口"""
    return {
        "status": "success",
        "message": "MCP endpoint is online",
        "session_id": session_id,
    }  # noqa: E501


@app.post("/api/v1/webhook/uptime-kuma")
async def uptime_kuma_webhook(payload: dict):
    """接收 Uptime Kuma 的 Webhook 报警，并触发前端全局通知"""
    monitor_name = payload.get("monitor", {}).get("name", "Unknown Service")
    status = payload.get("heartbeat", {}).get("status", 0)
    msg = payload.get("msg", "")

    if status == 0:
        alert_msg = f"🚨 [服务宕机报警] 核心系统离线: {monitor_name}\n详情: {msg}"
    else:
        alert_msg = f"✅ [服务恢复通知] 核心系统已重新上线: {monitor_name}"

    asyncio.create_task(notification_service.send_alert(alert_msg))
    return {"status": "success"}


@app.get("/")
async def root():
    """默认根路由"""
    return {
        "status": "success",
        "message": "Quant Agent 主网关已启动。请访问 /docs 查看接口文档。",
    }  # noqa: E501


# ==========================================
# --- AI Agent Chat API (SSE) ---
# ==========================================
STATIC_SUGGESTIONS = [
    {
        "title": "今日宏观风向",
        "prompt": "提取今天全球核心经济体的宏观大事件，并给出你的风险判断。",
    },  # noqa: E501
    {
        "title": "回测绩效归因",
        "prompt": "我的策略夏普比率 1.5，但最大回撤 25%，请分析可能的原因及改进建议。",
    },  # noqa: E501
    {
        "title": "量化代码 Debug",
        "prompt": "我有一个报错：RuntimeWarning: divide by zero encountered in scalar divide，在 Numpy 计算夏普比率时，如何安全处理？",
    },  # noqa: E501
    {
        "title": "交易心理建设",
        "prompt": "连续亏损导致心态失衡，作为量化交易员，该如何科学地执行熔断并调整心态？",
    },  # noqa: E501
    {
        "title": "期权策略套利",
        "prompt": "当前 VIX 较低，推荐一个适合中性震荡行情的期权卖方策略（如 Iron Condor）。",
    },  # noqa: E501
]

# 💡 动态组合词库：13(资产) * 10(指标) * 8(主题) * 7(动作) * 5(模板) = 可产生超过 36,000+ 种不重复的灵感  # noqa: E501
DYN_ASSETS = [
    "AAPL(苹果)",
    "TSLA(特斯拉)",
    "NVDA(英伟达)",
    "MSFT(微软)",
    "0700.HK(腾讯)",
    "09988.HK(阿里)",
    "BTC(比特币)",
    "ETH(以太坊)",
    "SPY(标普500)",
    "QQQ(纳指ETF)",
    "GLD(黄金ETF)",
    "USO(原油ETF)",
    "TLT(长牛美债)",
]  # noqa: E501
DYN_INDICATORS = [
    "双均线(MA)",
    "指数移动平均(EMA)",
    "MACD",
    "RSI",
    "布林带(BOLL)",
    "真实波幅(ATR)",
    "KDJ",
    "VWAP",
    "动量因子(Momentum)",
    "夏普比率(Sharpe)",
]  # noqa: E501
DYN_THEMES = [
    "基本面",
    "技术面",
    "资金面",
    "情绪面",
    "宏观政策",
    "期权隐含波动率(IV)",
    "量化统计套利",
    "跨市场对冲",
]  # noqa: E501
DYN_ACTIONS = [
    "写一个实盘策略框架",
    "分析最新的走势",
    "诊断可能存在的黑天鹅风险",
    "给出投资组合建议",
    "编写量化特征提取代码",
    "分析支撑位和压力位",
    "评估目前的估值水平",
]  # noqa: E501


@app.get("/api/v1/chat/suggestions")
async def get_chat_suggestions(limit: int = 10):
    import random

    selected = []

    # 随机生成直到满足 limit 数量
    while len(selected) < limit:
        if random.random() < 0.2:
            # 20% 概率抽取静态经典灵感
            item = random.choice(STATIC_SUGGESTIONS)
            if item not in selected:
                selected.append(item)
        else:
            # 80% 概率动态组合生成 (池子深度超万种)
            asset = random.choice(DYN_ASSETS)
            indicator = random.choice(DYN_INDICATORS)
            theme = random.choice(DYN_THEMES)
            action = random.choice(DYN_ACTIONS)

            # 随机模板引擎
            template_idx = random.randint(1, 5)
            if template_idx == 1:
                title = f"{asset} {theme}分析"
                prompt = f"请结合当前的{theme}，帮我{action}：{asset}。"
            elif template_idx == 2:
                title = f"{indicator} {asset}策略"
                prompt = f"我想要针对 {asset} 交易，请结合 {indicator} 指标，帮我{action}。"  # noqa: E501
            elif template_idx == 3:
                title = f"深挖 {asset} {theme}"
                prompt = f"目前 {asset} 的{theme}表现如何？结合 {indicator} 数据，{action}。"  # noqa: E501
            elif template_idx == 4:
                title = f"量化因子: {indicator}"
                prompt = f"我想利用 Pandas 计算 {asset} 的 {indicator} 因子，请{action}。"  # noqa: E501
            else:
                title = f"{asset} 风险预警"
                prompt = f"假设我重仓了 {asset}，请从{theme}的角度，结合 {indicator}，帮我{action}。"  # noqa: E501

            item = {"title": title, "prompt": prompt}
            # 简单去重
            if not any(x["title"] == item["title"] for x in selected):
                selected.append(item)

    return {"status": "success", "data": selected}


class ChatMessage(BaseModel):
    role: str
    content: Optional[Any] = None
    name: Optional[str] = None
    tool_calls: Optional[Any] = None
    tool_call_id: Optional[str] = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    session_id: Optional[str] = "default_api_session"


@app.post("/api/v1/chat")
async def chat_endpoint(request: ChatRequest, username: str = Depends(get_current_user)):  # noqa: E501
    """接收前端对话并调用 Hermes Agent (流式)"""
    global global_registry, global_llm_client, redis_client
    if not global_registry:
        raise HTTPException(status_code=503, detail="Tool Registry 未初始化")

    # 💡 性能优化：延迟导入 HermesAgent，降低启动内存
    from hermes_agent.agent import HermesAgent

    safe_session_id = f"user_{username}_{request.session_id or 'default_api_session'}"

    current_agent = HermesAgent(
        tool_registry=global_registry,
        system_prompt_path=os.path.abspath("AGENTS.md"),
        session_id=safe_session_id,
        llm_client=global_llm_client,
        redis_client=redis_client,
    )

    await current_agent.initialize()

    user_message = ""
    if request.messages and request.messages[-1].role == "user":
        last_content = request.messages[-1].content
        if last_content is not None and str(last_content).strip():
            user_message = str(last_content).strip()

            # 🛡️ 边界防御：防范前端传入恶意超大文本引发 Token 上下文溢出
            if len(user_message) > 20000:
                user_message = user_message[:20000] + "\n\n...[⚠️ 用户输入过长，已被系统安全机制自动截断保护]"  # noqa: E501

    async def generate_response():
        try:
            async for chunk in current_agent.chat_stream_async(
                user_message, attachments=None
            ):  # 暂时禁用图片识别，不传递 attachments  # noqa: E501
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except Exception as e:
            print(f"❌ [Chat API] Error: {e}")
            import traceback

            traceback.print_exc()
            error_event = {
                "type": "error",
                "content": f"\n\n> ⚠️ **Agent 引擎调用失败**: {str(e)}\n",
            }  # noqa: E501
            yield json.dumps(error_event, ensure_ascii=False) + "\n"

    return StreamingResponse(generate_response(), media_type="application/x-ndjson")


# ==========================================
# --- 历史会话管理 API (REST) ---
# ==========================================
@app.get("/api/v1/sessions")
async def get_sessions(
    user_id: Optional[int] = None,
    q: Optional[str] = None,
    username: str = Depends(get_current_user),
):  # noqa: E501
    """获取历史会话列表 (支持可选的 user_id 过滤与关键字搜索)"""

    def fetch_sessions():
        from sqlalchemy import String, cast

        with SessionLocal() as db:
            query = db.query(models.AgentSession)
            prefix = f"user_{username}_"
            query = query.filter(models.AgentSession.session_id.startswith(prefix))

            # 💡 穿透检索：如果有关键字，同时对会话标题和 JSON 消息内容进行深度模糊匹配
            if q:
                query = query.filter(
                    (models.AgentSession.title.ilike(f"%{q}%"))
                    | (cast(models.AgentSession.messages, String).ilike(f"%{q}%"))
                )

            # 按照更新时间倒序排列 (最近对话的在最前)
            records = query.order_by(models.AgentSession.updated_at.desc()).all()

            # 💡 动态概括标题：提取用户第一句话作为标题，并清理残留的“新对话”
            needs_commit = False
            for r in records:
                if r.title == "新对话" and r.messages:
                    for m in r.messages:
                        if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):  # noqa: E501
                            content_str = str(m.get("content")).strip()
                            if content_str:
                                r.title = content_str[:20] + ("..." if len(content_str) > 20 else "")  # noqa: E501
                                needs_commit = True
                                break

            # 如果有标题被成功概括，统一提交一次事务写回数据库，以后直接读取即可
            if needs_commit:
                db.commit()

            res_data = []
            for r in records:
                # 💡 修复：精确计算前端实际显示的条目数 (合并连续的 assistant 消息，过滤 system/tool)  # noqa: E501
                display_count = 0
                if r.messages:
                    last_role = None
                    for m in r.messages:
                        if not isinstance(m, dict):
                            continue
                        role = m.get("role")
                        if role in ["system", "tool"]:
                            continue
                        if role == "user":
                            display_count += 1
                            last_role = "user"
                        elif role == "assistant":
                            if last_role != "assistant":
                                display_count += 1
                            last_role = "assistant"

                res_data.append(
                    {
                        "session_id": r.session_id[len(prefix) :] if r.session_id.startswith(prefix) else r.session_id,  # noqa: E501
                        "title": r.title,
                        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else "",  # noqa: E501
                        "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else "",  # noqa: E501
                        "message_count": display_count,
                    }
                )
            return res_data

    try:
        sessions = await asyncio.to_thread(fetch_sessions)
        return {"status": "success", "data": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/sessions/{session_id}")
async def get_session_history(session_id: str, username: str = Depends(get_current_user)):  # noqa: E501
    """获取指定会话的历史详细消息"""
    safe_session_id = f"user_{username}_{session_id}"

    def fetch_history():
        with SessionLocal() as db:
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()  # noqa: E501
            if record:
                return record.messages
            return []

    try:
        messages = await asyncio.to_thread(fetch_history)
        return {"status": "success", "data": messages}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/sessions")
async def delete_all_sessions(username: str = Depends(get_current_user)):
    """删除当前用户的所有历史会话 (同时清理冷热两层数据)"""
    prefix = f"user_{username}_"

    def drop_all():
        with SessionLocal() as db:
            records = db.query(models.AgentSession).filter(models.AgentSession.session_id.startswith(prefix)).all()  # noqa: E501
            if not records:
                return False
            for r in records:
                db.delete(r)
            db.commit()
            return True

    try:
        # 1. 尝试从 PG 数据库中删除冷数据 (放入线程池防阻塞)
        deleted = await asyncio.to_thread(drop_all)

        # 2. 从 Redis 缓存中清除热数据
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=f"hermes:memory:{prefix}*", count=100)  # noqa: E501
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break

        if not deleted:
            return {"status": "success", "message": "当前无历史会话记录"}

        return {"status": "success", "message": "所有历史会话已彻底删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v1/sessions/{session_id}")
async def delete_session(session_id: str, username: str = Depends(get_current_user)):
    """删除指定的历史会话 (同时清理冷热两层数据)"""
    safe_session_id = f"user_{username}_{session_id}"

    def drop_session():
        with SessionLocal() as db:
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()  # noqa: E501
            if not record:
                return False
            db.delete(record)
            db.commit()
            return True

    try:
        # 1. 尝试从 PG 数据库中删除冷数据 (放入线程池防阻塞)
        deleted = await asyncio.to_thread(drop_session)

        # 2. 从 Redis 缓存中清除热数据，防止脏数据在下次请求时诈尸复活
        await redis_client.delete(f"hermes:memory:{safe_session_id}")

        if not deleted:
            raise HTTPException(status_code=404, detail="会话记录不存在")

        return {"status": "success", "message": f"会话 {session_id} 已彻底删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# --- 标准 MCP (Model Context Protocol) SSE 通讯层 ---
# ==========================================
@app.get("/mcp/sse")
async def mcp_sse(request: Request):
    """MCP SSE 协议端点：建立长连接，下发双向通讯路由"""
    session_id = str(uuid.uuid4())

    async def sse_generator():
        post_url = f"{request.url.scheme}://{request.url.netloc}/mcp/message?session_id={session_id}"
        yield f"event: endpoint\ndata: {post_url}\n\n"

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"mcp_session_{session_id}")
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0),
                        timeout=15.0,
                    )  # noqa: E501
                    if msg and msg["type"] == "message":
                        message_str = msg["data"].decode("utf-8") if isinstance(msg["data"], bytes) else msg["data"]  # noqa: E501
                        yield f"data: {message_str}\n\n"
                    elif msg is None:
                        yield ": keep-alive\n\n"
                except asyncio.TimeoutError:
                    # 按照 SSE 规范，以冒号开头的行是注释，客户端会自动忽略，但能保持 TCP 连接活跃  # noqa: E501
                    yield ": keep-alive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.unsubscribe()
            finally:
                await pubsub.close()

    return StreamingResponse(sse_generator(), media_type="text/event-stream")


@app.post("/mcp/message")
async def mcp_message(session_id: str, payload: dict):
    """MCP HTTP 协议端点：接收客户端发来的 JSON-RPC 指令"""
    response_payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "status": "success",
                "message": f"Action {payload.get('method')} executed by Hermes Agent",
            },
        }
    )

    # 💡 分布式广播：不论是哪台机器建立的 SSE 连接，都能通过 Redis 通道精准投递，完美支持负载均衡  # noqa: E501
    receivers = await redis_client.publish(f"mcp_session_{session_id}", response_payload)  # noqa: E501
    if receivers == 0:
        raise HTTPException(status_code=404, detail="Session not found or expired on any cluster node")  # noqa: E501

    return "Accepted"


# 挂载 React 编译后的静态资源目录 (JS/CSS 等)
# 注意: 如果前端使用 Create React App 构建，产物目录可能是 "build" 而不是 "dist"
dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))  # noqa: E501
assets_dir = os.path.join(dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/monitor")
async def monitor_page():
    """代理 React 编译后的入口 index.html"""
    html_path = os.path.join(dist_dir, "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="前端编译文件不存在，请先执行 npm run build")  # noqa: E501
    return FileResponse(html_path)
