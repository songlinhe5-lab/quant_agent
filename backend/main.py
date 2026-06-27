import asyncio
import os
import sys
import warnings

# 💡 过滤 macOS/Linux 下 Uvicorn 热重载强退时，底层触发的无害 POSIX 信号量泄漏警告
warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")

from contextlib import asynccontextmanager
import secrets
import socket
import json
import time
from typing import Optional, Any
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, HTTPBasic, HTTPBasicCredentials
from fastapi import Cookie
from jose import JWTError, jwt
import uuid
import prometheus_client

# 将项目根目录加入 sys.path，避免直接运行 python backend/main.py 时出现 ModuleNotFoundError: No module named 'backend'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

# 🚨 全局线程死锁防御：为底层所有未显式指定 timeout 的同步 Socket 注入 15 秒超时。
# 系统中如 AKShare, ChromaDB 内部高度依赖 requests 且未暴露 timeout 参数。
# 若外部接口发生 TCP 假死，asyncio.to_thread 的物理线程将永久阻塞，最终彻底榨干 FastAPI 全局线程池！
# 设定全局默认超时是封堵第三方同步库“线程黑洞”的最底线安全手段。
socket.setdefaulttimeout(15.0)

from hermes_agent.agent import HermesAgent
from hermes_agent.tool_registry import ToolRegistry
from openai import AsyncOpenAI
from backend.core.database import engine, async_engine, Base, SessionLocal
from backend.core import models

# 自动创建数据库表与必要扩展
try:
    from sqlalchemy import text
    with engine.begin() as conn:
        is_pg = conn.dialect.name == 'postgresql'
        if is_pg:
            # 1. 自动启用所需的所有 PG 扩展 (向量搜索 vector + 模糊搜索 pg_trgm)
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
            
    Base.metadata.create_all(bind=engine)
    
    with engine.begin() as conn:
        if is_pg:
            # 2. 表创建完成后，挂载额外的 GIN 高性能索引
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_symbol ON tickers USING gin (symbol gin_trgm_ops);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS trgm_idx_ticker_name ON tickers USING gin (name gin_trgm_ops);"))
            print("✅ [System] PostgreSQL pgvector 与 pg_trgm 扩展及全局索引挂载就绪！")
except Exception as e:
    print(f"⚠️ [System] 自动创建数据库表失败 (请确认数据库服务已启动): {e}")

from backend.core.market_engine import manager
from backend.core.redis_client import redis_client, redis_batch_writer, l1_cached_redis
from backend.services.futu_service import futu_service
from backend.services.notification_service import notification_service
from backend.services.ticker_service import ticker_service
from backend.services.yfinance_service import yf_service
from backend.services.finnhub_service import finnhub_service
from backend.services.sentiment_tracker import sentiment_tracker
from backend.services.system_monitor_service import system_monitor_service
from backend.services.screener_service import screener_service
from backend.services.fred_service import fred_service
from backend.services.llm_service import llm_service
from backend.core.middleware import AccessLogMiddleware

# --- 业务模块路由 ---
from backend.routers.market import router as market_router
from backend.routers.trade import router as trade_router
from backend.routers.macro import router as macro_router
from backend.routers.preferences import router as preferences_router
from backend.routers.auth import router as auth_router, get_password_hash
from backend.routers.backtest import router as backtest_router
from backend.routers.screener import router as screener_router
from backend.routers.search import router as search_router
from backend.routers.strategy import router as strategy_router
from backend.routers.oms import router as oms_router

# --- 全局单例与连接池 ---
global_registry = None
global_llm_client = None

# 引入自检脚本中的深度测试方法
from scripts.test_all_services import test_yfinance_service, test_futu_service, test_notification_service, test_fred_service

@asynccontextmanager
async def lifespan(app: FastAPI): # type: ignore
    """系统的全局生命周期管理器 (替代废弃的 on_event 钩子)"""
    global global_registry, global_llm_client

    # === 启动阶段 (Startup) ===
    print("\n🚀 [Startup] 正在执行后端核心服务深度自检...")
    
    # 💡 性能安全防御：全局限制 asyncio 与 AnyIO 的最大物理线程池容量，防止 OOM
    import concurrent.futures
    try:
        loop = asyncio.get_running_loop()
        # 限制 asyncio.to_thread() 的默认线程池大小，防止外部接口卡死时物理线程无限飙升耗尽内存
        executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=64, 
            thread_name_prefix="GlobalAsyncioWorker"
        )
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
            admin = db.query(models.User).filter(models.User.username == "admin").first()
            if not admin:
                admin_user = models.User(
                    username="admin",
                    email="admin@quant.local",
                    hashed_password=get_password_hash("admin")
                )
                db.add(admin_user)
                db.commit()
                print("✅ [Startup] 默认管理员账号 (admin/admin) 初始化成功！")
    except Exception as e:
        print(f"⚠️ [Startup] 管理员账号初始化失败: {e}")
    
    # 1. 运行雅虎财经测试 (防限流：开发期间若经常 reload，可在环境配置中加上 SKIP_YF_TEST=1 跳过)
    # if os.getenv("SKIP_YF_TEST") != "1":
    #     await test_yfinance_service()
    
    # 💡 增加容灾包裹：防止外部 API 或富途网关不通导致整个 Docker 容器死循环无法启动
    try:
        # 2. 运行富途测试，并保留 OpenD 连接用于后续业务路由 (close_after=False)
        await test_futu_service(close_after=False) # type: ignore
    except Exception as e:
        print(f"⚠️ [Startup] 富途 OpenD 接口测试失败，已自动降级跳过: {e}")
        
    try:
        # 3. 运行 Redis 连通性与系统通知测试
        await test_notification_service() # type: ignore
        # 4. 运行 FRED 宏观数据接口测试
        await test_fred_service() # type: ignore
    except Exception as e:
        print(f"⚠️ [Startup] 核心外部服务连通性预检失败: {e}")
    
    print("\n🎉 [Startup] 所有后端服务自检完成，API 网关启动就绪！\n")

    # 🧠 [Agent] 初始化 AI 主脑相关服务
    print("🛠️  [Agent Startup] 装载量化 Tools 沙箱网络客户端...")
    global_registry = ToolRegistry()
    print(f"✅ [Agent Startup] 成功挂载 {len(global_registry.tools)} 个 AI Agent 核心工具！")
    
    print("🔌 [Agent Startup] 初始化全局共享的大模型连接池...")
    global_llm_client = AsyncOpenAI(
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    )

    # 🚀 启动事件循环健康监控探针
    loop_monitor_task = asyncio.create_task(system_monitor_service.event_loop_monitor_daemon())

    await manager.start_background_tasks() # type: ignore
    asyncio.create_task(notification_service.send_alert("✅ [Quant Agent] 量化引擎数据网关已成功连接并启动！"))
    
    asyncio.create_task(finnhub_service._insider_transactions_marquee_daemon()) # 启动高管内幕交易跑马灯守护进程
    yield # 挂起，此时 FastAPI 正式对外提供 HTTP 与 WS 服务

    
    # === 销毁阶段 (Shutdown) ===
    print("🛑 正在关闭后端服务，释放资源...")
    try:
        tasks_to_await = []
            
        if 'loop_monitor_task' in locals() and not loop_monitor_task.done():
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
    except Exception as e:
        pass

    try:
        # 🧠 [Agent] 关闭 AI 主脑连接
        if global_llm_client:
            await global_llm_client.close() # type: ignore
            
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
        await redis_client.aclose() # type: ignore
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

app = FastAPI(title="Quant Agent Data Gateway", lifespan=lifespan)

# ==========================================
# --- Prometheus 监控指标暴露 ---
# ==========================================
metrics_security = HTTPBasic()

def verify_metrics_auth(credentials: HTTPBasicCredentials = Depends(metrics_security)):
    # 可在 .env 中配置 METRICS_USER 和 METRICS_PASS，缺省均为 admin
    # 💡 增加 .encode("utf-8") 防御：防止输入带有非 ASCII 字符导致 secrets.compare_digest 触发 TypeError 崩溃
    current_user_bytes = credentials.username.encode("utf-8")
    current_pass_bytes = credentials.password.encode("utf-8")
    env_user_bytes = os.getenv("METRICS_USER", "admin").encode("utf-8")
    env_pass_bytes = os.getenv("METRICS_PASS", "admin").encode("utf-8")
    
    correct_username = secrets.compare_digest(current_user_bytes, env_user_bytes)
    correct_password = secrets.compare_digest(current_pass_bytes, env_pass_bytes)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401, detail="Unauthorized metrics access", headers={"WWW-Authenticate": "Basic"}
        )
    return credentials.username

@app.get("/metrics", include_in_schema=False)
def metrics(username: str = Depends(verify_metrics_auth)):
    # 💡 性能修复：因为 generate_latest 是同步阻塞操作，移除 async 使其运行在线程池中，防止阻塞网关的高频事件循环
    return Response(content=prometheus_client.generate_latest(), media_type=prometheus_client.CONTENT_TYPE_LATEST)

# ==========================================
# 全局 API 限流中间件 (Rate Limiter)
# ==========================================
RATE_LIMIT = 100  # 每个 IP 在时间窗口内的最大请求数
RATE_WINDOW = 60  # 时间窗口 (秒)

@app.middleware("http")
async def pyinstrument_profiler_middleware(request: Request, call_next):
    """
    优雅的 pyinstrument 性能分析中间件
    使用方法: 在任意 GET/POST 接口后加上 ?profile=true
    将直接在浏览器中返回直观的交互式函数调用树 HTML 报告，彻底取代难用的 cProfile。
    """
    if request.query_params.get("profile") == "true":
        try:
            from pyinstrument import Profiler
            from fastapi.responses import HTMLResponse
            
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
    if not request.url.path.startswith("/assets") and request.url.path not in ["/", "/monitor", "/health"]:
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"
        
        try:
            # 使用 Redis Pipeline 保证高频操作的原子性与极致性能
            async with redis_client.pipeline() as pipe:
                await pipe.incr(key)
                await pipe.expire(key, RATE_WINDOW, nx=True) # 仅在键刚创建时设置过期时间 (需 Redis 7.0+)
                results = await pipe.execute()
            
            current_requests = results[0]
            if current_requests > RATE_LIMIT:
                return JSONResponse(
                    status_code=429,
                    content={"status": "error", "message": f"请求过于频繁，限制为 {RATE_LIMIT}次/{RATE_WINDOW}秒。"}
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
    if process_time > 1.5 and not request.url.path.startswith("/api/chat"): # 过滤掉原本就耗时的 AI 对话
        print(f"🐢 [Slow Request] {request.method} {request.url.path} 耗时: {process_time:.2f}s")
        asyncio.create_task(
            asyncio.to_thread(
                system_monitor_service._save_performance_log,
                "slow_request",
                process_time * 1000,
                f"{request.method} {request.url.path}"
            )
        )
    return response

# 允许 Vite 等前端本地代理发起请求（SEC-11：CORS 白名单配置，禁止 *）
# 生产环境应在 .env 中配置 ALLOWED_ORIGINS 环境变量，多个域名用逗号分隔
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    allow_credentials=True,
)

# 挂载全局请求访问与 Prometheus 性能监控中间件
app.add_middleware(AccessLogMiddleware)

# 挂载所有重构至 routers 目录下的纯净业务路由（添加 /api/v1/ 版本前缀，符合 SEC-01 安全规范）
app.include_router(market_router, prefix="/api/v1")
app.include_router(trade_router, prefix="/api/v1")
app.include_router(macro_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(backtest_router, prefix="/api/v1")
app.include_router(screener_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(strategy_router, prefix="/api/v1")
app.include_router(oms_router, prefix="/api/v1")

# ==========================================
# --- JWT 鉴权依赖 (SSR & Client 兼容) ---
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
ALGORITHM = "HS256"
security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    refresh_token: Optional[str] = Cookie(None)
):
    """从 Header (Bearer) 或 Cookie (SSR) 中提取并验证 JWT Token"""
    token = credentials.credentials if credentials else refresh_token
    if token == "null": # 处理前端在 Token 未就绪时发来的 "null" 字符串
        token = refresh_token
    if not token:
        raise HTTPException(status_code=401, detail="请求未携带合法 Token，拒绝访问")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if not username: raise HTTPException(status_code=401, detail="Token 载荷非法 (缺失 sub)")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

def _read_file_sync(target_file: str, ext: str) -> str:
    content = ""
    if ext in ['.txt', '.md', '.csv']:
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()
    elif ext == '.pdf':
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
                            clean_row = [str(cell).replace('\n', ' ').strip() if cell else "" for cell in row]
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
    # 严格过滤掉斜杠和反斜杠，并消除可能存在的 .. 序列，防止黑客通过构造如 ../../../.env 的 Ticker 来读取系统机密文件
    safe_ticker = re.sub(r'[^A-Z0-9_.-]', '', ticker.upper()).replace("..", "")
    if not safe_ticker:
        raise HTTPException(status_code=400, detail="非法的股票代码参数")

    reports_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "reports"))
    os.makedirs(reports_dir, exist_ok=True)
    search_pattern = os.path.join(reports_dir, f"*{safe_ticker}*.*")
    matched_files = glob.glob(search_pattern)

    if not matched_files:
        return {"status": "error", "message": f"未在财报目录下找到包含 {safe_ticker} 的财报文件。"}

    target_file = matched_files[0]
    ext = os.path.splitext(target_file)[1].lower()

    try:
        if ext not in ['.txt', '.md', '.csv', '.pdf']:
            return {"status": "error", "message": f"不支持的文件格式: {ext}。"}
        content = await asyncio.to_thread(_read_file_sync, target_file, ext)
        max_chars = 15000
        chunks = [content[i:i+max_chars] for i in range(0, len(content), max_chars)]
        if not chunks:
            return {"status": "error", "message": "文件内容提取为空。"}
        if chunk_index < 0 or chunk_index >= len(chunks):
            return {"status": "error", "message": f"chunk_index 越界。有效范围: 0 到 {len(chunks)-1}"}

        return {"status": "success", "file_path": target_file, "total_chunks": len(chunks), "current_chunk_index": chunk_index, "content": chunks[chunk_index], "message": f"成功读取财报文件第 {chunk_index + 1}/{len(chunks)} 部分。"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class YFinanceToggle(BaseModel):
    enabled: bool

@app.post("/api/v1/settings/yfinance")
async def toggle_yfinance(payload: YFinanceToggle):
    """前端一键控制 YFinance 兜底开关"""
    await l1_cached_redis.set("quant:settings:yfinance_enabled", "1" if payload.enabled else "0")
    return {"status": "success", "message": f"YFinance 兜底已{'开启' if payload.enabled else '关闭'}"}

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

    # 2. 检查 Futu OpenD 连接状态 (业务依赖，断开则标记为降级 degraded)
    components["futu"] = futu_service.status
    if futu_service.status != "CONNECTED" and overall_status == "healthy":
        overall_status = "degraded"

    # 3. YFinance 属于外部高频受限 API，防止 Docker 轮询导致 IP 被封，做跳过处理
    components["yfinance"] = "skipped (prevent rate limits)"

    # 4. 监控 asyncio 默认线程池状态 (供 asyncio.to_thread 手动派发的任务使用)
    loop = asyncio.get_running_loop()
    executor = getattr(loop, "_default_executor", None)
    if executor is not None and hasattr(executor, "_max_workers"):
        components["asyncio_thread_pool"] = {
            "max_workers": executor._max_workers,         # 线程池最大容量
            "spawned_threads": len(executor._threads),    # 当前已孵化的真实物理线程数
            "pending_tasks": executor._work_queue.qsize() # 正在排队等待空闲线程的任务数
        }
    else:
        components["asyncio_thread_pool"] = "idle (lazy initialized)"

    # 5. 监控 FastAPI/AnyIO 底层线程池状态 (供同步 def 路由使用)
    try:
        from anyio.to_thread import current_default_thread_limiter
        limiter = current_default_thread_limiter()
        components["fastapi_thread_pool"] = {
            "max_workers": limiter.total_tokens,          # 允许并发执行的最大请求数 (默认40)
            "idle_workers": limiter.available_tokens,     # 当前空闲可用的 Worker 数量
            "busy_workers": limiter.total_tokens - limiter.available_tokens
        }
    except Exception as e:
        components["fastapi_thread_pool"] = f"unknown ({e})"

    response_data = {"status": overall_status, "components": components}
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=response_data)
    return response_data

@app.get("/mcp")
async def mcp_health_check(session_id: Optional[str] = None):
    """兼容 Uptime Kuma 等监控工具针对 MCP 探针的健康检查接口"""
    return {"status": "success", "message": "MCP endpoint is online", "session_id": session_id}

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
    return {"status": "success", "message": "Quant Agent 主网关已启动。请访问 /docs 查看接口文档。"}

# ==========================================
# --- AI Agent Chat API (SSE) ---
# ==========================================
STATIC_SUGGESTIONS = [
    {"title": "今日宏观风向", "prompt": "提取今天全球核心经济体的宏观大事件，并给出你的风险判断。"},
    {"title": "回测绩效归因", "prompt": "我的策略夏普比率 1.5，但最大回撤 25%，请分析可能的原因及改进建议。"},
    {"title": "量化代码 Debug", "prompt": "我有一个报错：RuntimeWarning: divide by zero encountered in scalar divide，在 Numpy 计算夏普比率时，如何安全处理？"},
    {"title": "交易心理建设", "prompt": "连续亏损导致心态失衡，作为量化交易员，该如何科学地执行熔断并调整心态？"},
    {"title": "期权策略套利", "prompt": "当前 VIX 较低，推荐一个适合中性震荡行情的期权卖方策略（如 Iron Condor）。"}
]

# 💡 动态组合词库：13(资产) * 10(指标) * 8(主题) * 7(动作) * 5(模板) = 可产生超过 36,000+ 种不重复的灵感
DYN_ASSETS = ["AAPL(苹果)", "TSLA(特斯拉)", "NVDA(英伟达)", "MSFT(微软)", "0700.HK(腾讯)", "09988.HK(阿里)", "BTC(比特币)", "ETH(以太坊)", "SPY(标普500)", "QQQ(纳指ETF)", "GLD(黄金ETF)", "USO(原油ETF)", "TLT(长牛美债)"]
DYN_INDICATORS = ["双均线(MA)", "指数移动平均(EMA)", "MACD", "RSI", "布林带(BOLL)", "真实波幅(ATR)", "KDJ", "VWAP", "动量因子(Momentum)", "夏普比率(Sharpe)"]
DYN_THEMES = ["基本面", "技术面", "资金面", "情绪面", "宏观政策", "期权隐含波动率(IV)", "量化统计套利", "跨市场对冲"]
DYN_ACTIONS = ["写一个实盘策略框架", "分析最新的走势", "诊断可能存在的黑天鹅风险", "给出投资组合建议", "编写量化特征提取代码", "分析支撑位和压力位", "评估目前的估值水平"]

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
                prompt = f"我想要针对 {asset} 交易，请结合 {indicator} 指标，帮我{action}。"
            elif template_idx == 3:
                title = f"深挖 {asset} {theme}"
                prompt = f"目前 {asset} 的{theme}表现如何？结合 {indicator} 数据，{action}。"
            elif template_idx == 4:
                title = f"量化因子: {indicator}"
                prompt = f"我想利用 Pandas 计算 {asset} 的 {indicator} 因子，请{action}。"
            else:
                title = f"{asset} 风险预警"
                prompt = f"假设我重仓了 {asset}，请从{theme}的角度，结合 {indicator}，帮我{action}。"
                
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
async def chat_endpoint(request: ChatRequest, username: str = Depends(get_current_user)):
    """接收前端对话并调用 Hermes Agent (流式)"""
    global global_registry, global_llm_client, redis_client
    if not global_registry:
        raise HTTPException(status_code=503, detail="Tool Registry 未初始化")

    safe_session_id = f"user_{username}_{request.session_id or 'default_api_session'}"
    
    current_agent = HermesAgent(
        tool_registry=global_registry,
        system_prompt_path=os.path.abspath("AGENTS.md"),
        session_id=safe_session_id,
        llm_client=global_llm_client,
        redis_client=redis_client
    )
    
    await current_agent.initialize()

    user_message = ""
    if request.messages and request.messages[-1].role == "user":
        last_content = request.messages[-1].content
        if last_content is not None and str(last_content).strip():
            user_message = str(last_content).strip()
            
            # 🛡️ 边界防御：防范前端传入恶意超大文本引发 Token 上下文溢出
            if len(user_message) > 20000:
                user_message = user_message[:20000] + "\n\n...[⚠️ 用户输入过长，已被系统安全机制自动截断保护]"

    async def generate_response():
        try:
            async for chunk in current_agent.chat_stream_async(user_message, attachments=None): # 暂时禁用图片识别，不传递 attachments
                yield json.dumps(chunk, ensure_ascii=False) + "\n"
        except Exception as e:
            print(f"❌ [Chat API] Error: {e}")
            import traceback
            traceback.print_exc()
            error_event = {"type": "error", "content": f"\n\n> ⚠️ **Agent 引擎调用失败**: {str(e)}\n"}
            yield json.dumps(error_event, ensure_ascii=False) + "\n"
            
    return StreamingResponse(generate_response(), media_type="application/x-ndjson")

# ==========================================
# --- 历史会话管理 API (REST) ---
# ==========================================
@app.get("/api/v1/sessions")
async def get_sessions(user_id: Optional[int] = None, q: Optional[str] = None, username: str = Depends(get_current_user)):
    """获取历史会话列表 (支持可选的 user_id 过滤与关键字搜索)"""
    def fetch_sessions():
        from sqlalchemy import cast, String
        with SessionLocal() as db:
            query = db.query(models.AgentSession)
            prefix = f"user_{username}_"
            query = query.filter(models.AgentSession.session_id.startswith(prefix))
            
            # 💡 穿透检索：如果有关键字，同时对会话标题和 JSON 消息内容进行深度模糊匹配
            if q:
                query = query.filter(
                    (models.AgentSession.title.ilike(f"%{q}%")) | 
                    (cast(models.AgentSession.messages, String).ilike(f"%{q}%"))
                )
            
            # 按照更新时间倒序排列 (最近对话的在最前)
            records = query.order_by(models.AgentSession.updated_at.desc()).all()
            
            # 💡 动态概括标题：提取用户第一句话作为标题，并清理残留的“新对话”
            needs_commit = False
            for r in records:
                if r.title == "新对话" and r.messages:
                    for m in r.messages:
                        if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                            content_str = str(m.get("content")).strip()
                            if content_str:
                                r.title = content_str[:20] + ("..." if len(content_str) > 20 else "")
                                needs_commit = True
                                break
            
            # 如果有标题被成功概括，统一提交一次事务写回数据库，以后直接读取即可
            if needs_commit:
                db.commit()
                
            res_data = []
            for r in records:
                # 💡 修复：精确计算前端实际显示的条目数 (合并连续的 assistant 消息，过滤 system/tool)
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
                            
                res_data.append({
                    "session_id": r.session_id[len(prefix):] if r.session_id.startswith(prefix) else r.session_id,
                    "title": r.title,
                    "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else "",
                    "updated_at": r.updated_at.isoformat() if getattr(r, "updated_at", None) else "",
                    "message_count": display_count
                })
            return res_data
    try:
        sessions = await asyncio.to_thread(fetch_sessions)
        return {"status": "success", "data": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/sessions/{session_id}")
async def get_session_history(session_id: str, username: str = Depends(get_current_user)):
    """获取指定会话的历史详细消息"""
    safe_session_id = f"user_{username}_{session_id}"
    def fetch_history():
        with SessionLocal() as db:
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()
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
            records = db.query(models.AgentSession).filter(models.AgentSession.session_id.startswith(prefix)).all()
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
            cursor, keys = await redis_client.scan(cursor=cursor, match=f"hermes:memory:{prefix}*", count=100)
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
            record = db.query(models.AgentSession).filter(models.AgentSession.session_id == safe_session_id).first()
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
# --- 系统性能监控日志 API ---
# ==========================================
@app.get("/api/system/performance-logs")
async def get_performance_logs(limit: int = 100, username: str = Depends(get_current_user)):
    """获取系统性能监控日志 (慢请求与事件循环卡顿)"""
    def fetch_logs():
        with SessionLocal() as db:
            logs = db.query(models.PerformanceLog).order_by(models.PerformanceLog.timestamp.desc()).limit(limit).all()
            return [{
                "id": log.id,
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
                "log_type": log.log_type,
                "duration_ms": log.duration_ms,
                "endpoint": log.endpoint,
                "details": log.details
            } for log in logs]
    
    try:
        data = await asyncio.to_thread(fetch_logs)
        return {"status": "success", "data": data}
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
                    msg = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0), timeout=15.0)
                    if msg and msg["type"] == "message":
                        message_str = msg['data'].decode('utf-8') if isinstance(msg['data'], bytes) else msg['data']
                        yield f"data: {message_str}\n\n"
                    elif msg is None:
                        yield ": keep-alive\n\n"
                except asyncio.TimeoutError:
                    # 按照 SSE 规范，以冒号开头的行是注释，客户端会自动忽略，但能保持 TCP 连接活跃
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
    response_payload = json.dumps({
        "jsonrpc": "2.0",
        "id": payload.get("id"),
        "result": {
            "status": "success", 
            "message": f"Action {payload.get('method')} executed by Hermes Agent"
        }
    })
    
    # 💡 分布式广播：不论是哪台机器建立的 SSE 连接，都能通过 Redis 通道精准投递，完美支持负载均衡
    receivers = await redis_client.publish(f"mcp_session_{session_id}", response_payload)
    if receivers == 0:
        raise HTTPException(status_code=404, detail="Session not found or expired on any cluster node")
        
    return "Accepted"

# 挂载 React 编译后的静态资源目录 (JS/CSS 等)
# 注意: 如果前端使用 Create React App 构建，产物目录可能是 "build" 而不是 "dist"
dist_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
assets_dir = os.path.join(dist_dir, "assets")
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

@app.get("/monitor")
async def monitor_page():
    """代理 React 编译后的入口 index.html"""
    html_path = os.path.join(dist_dir, "index.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="前端编译文件不存在，请先执行 npm run build")
    return FileResponse(html_path)