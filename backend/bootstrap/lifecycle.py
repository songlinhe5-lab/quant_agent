"""
应用生命周期管理器 (Startup / Shutdown)
从 main.py 迁出 (ARCH-01)
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.core import models
from backend.core.database import AsyncSessionLocal, SessionLocal, async_engine, engine
from backend.core.logger import logger
from backend.core.redis_client import redis_batch_writer, redis_client
from backend.core.security import get_password_hash
from backend.services.fred_service import fred_service
from backend.services.futu_service import futu_service
from backend.services.llm_service import llm_service
from backend.services.market_engine import manager
from backend.services.notification_service import notification_service
from backend.services.system_monitor_service import system_monitor_service
from backend.services.yfinance_service import yf_service

# 全局单例 (供 chat router 等模块引用)
global_registry = None
global_llm_client = None

# 引入自检脚本中的深度测试方法（可选，仅本地开发时可用）
try:
    from scripts.test_all_services import (
        test_fred_service,
        test_futu_service,
        test_notification_service,
    )
except ImportError:
    test_fred_service = None
    test_futu_service = None
    test_notification_service = None


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """系统的全局生命周期管理器"""
    global global_registry, global_llm_client

    # === 启动阶段 (Startup) ===
    print("\n🚀 [Startup] 正在执行后端核心服务深度自检...")

    # 全局限制 asyncio 与 AnyIO 的最大物理线程池容量，防止 OOM
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="GlobalAsyncioWorker")
        loop.set_default_executor(executor)

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
                    hashed_password=get_password_hash("admin"),
                )
                db.add(admin_user)
                db.commit()
                print("✅ [Startup] 默认管理员账号 (admin/admin) 初始化成功！")
    except Exception as e:
        print(f"⚠️ [Startup] 管理员账号初始化失败: {e}")

    # 容灾包裹：防止外部 API 不通导致容器死循环无法启动
    try:
        # 2. 连接 Futu OpenD
        from backend.services.futu import push_handler

        push_handler.set_main_loop(asyncio.get_running_loop())
        await asyncio.wait_for(asyncio.to_thread(futu_service.connect), timeout=15.0)
        print(f"✅ [Startup] Futu OpenD 连接状态: {futu_service.status}")
    except asyncio.TimeoutError:
        print("⚠️ [Startup] 富途 OpenD 连接超时 (15s)，已自动降级跳过")
    except Exception as e:
        print(f"⚠️ [Startup] 富途 OpenD 连接失败，已自动降级跳过: {e}")

    try:
        # 3. Redis 连通性与系统通知测试
        if test_notification_service is not None:
            await asyncio.wait_for(test_notification_service(), timeout=10.0)
        # 4. FRED 宏观数据接口测试
        if test_fred_service is not None:
            await asyncio.wait_for(test_fred_service(), timeout=10.0)
    except asyncio.TimeoutError:
        print("⚠️ [Startup] 核心外部服务预检超时 (10s)，已自动降级跳过")
    except Exception as e:
        print(f"⚠️ [Startup] 核心外部服务连通性预检失败: {e}")

    print("\n🎉 [Startup] 所有后端服务自检完成，API 网关启动就绪！\n")

    # 🧠 [Agent] 初始化 AI 主脑相关服务
    print("🛠️  [Agent Startup] 装载量化 Tools 沙箱网络客户端...")
    from hermes_agent.tool_registry import ToolRegistry

    global_registry = ToolRegistry()
    print(f"✅ [Agent Startup] 成功挂载 {len(global_registry.tools)} 个 AI Agent 核心工具！")

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
    loop_monitor_task = asyncio.create_task(system_monitor_service.event_loop_monitor_daemon())

    await manager.start_background_tasks()

    asyncio.create_task(notification_service.send_alert("✅ [Quant Agent] 量化引擎数据网关已成功连接并启动！"))

    # 🚀 NAV 快照守护进程 (每 5 分钟)
    async def _nav_snapshot_daemon():
        while True:
            try:
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
                            key = f"quant:risk:nav_snapshots:{market}"
                            await redis_client.lpush(key, json.dumps({"ts": time.time(), "nav": nav}))
                            await redis_client.ltrim(key, 0, 287)
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
            await asyncio.sleep(300)

    nav_snapshot_task = asyncio.create_task(_nav_snapshot_daemon())
    print("✅ [Startup] NAV 快照守护进程已启动 (每 5 分钟)")

    # 🚀 OMS 持仓同步守护进程 (每 30 秒)
    async def _oms_position_sync_daemon():
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
            await asyncio.sleep(30)

    oms_position_task = asyncio.create_task(_oms_position_sync_daemon())
    print("✅ [Startup] OMS 持仓同步守护进程已启动 (每 30 秒)")

    # 🚀 BotRuntimeManager 恢复
    from backend.services.bot_runtime import bot_runtime

    try:
        restored = await bot_runtime.restore_bots_from_redis()
        print(f"✅ [Startup] BotRuntimeManager 已启动 (恢复 {restored} 个 Bot)")
    except Exception as e:
        logger.warning(f"[Startup] BotRuntimeManager 恢复失败: {e}")

    # 🚀 AlgoEngine 恢复
    from backend.services.algo_engine import algo_engine

    try:
        algo_restored = await algo_engine.restore_from_redis()
        print(f"✅ [Startup] AlgoEngine 已启动 (恢复 {algo_restored} 个算法订单)")
    except Exception as e:
        logger.warning(f"[Startup] AlgoEngine 恢复失败: {e}")

    # 🚀 MarketEngine broadcast_loop
    try:
        await manager.start_background_tasks()
        print("✅ [Startup] MarketEngine broadcast_loop 已启动")
    except Exception as e:
        logger.warning(f"[Startup] MarketEngine 启动失败: {e}")

    yield  # 挂起，FastAPI 正式对外提供服务

    # === 销毁阶段 (Shutdown) ===
    print("🛑 正在关闭后端服务，释放资源...")

    try:
        tasks_to_await = []

        if "nav_snapshot_task" in locals() and not nav_snapshot_task.done():
            nav_snapshot_task.cancel()
            tasks_to_await.append(nav_snapshot_task)

        if "oms_position_task" in locals() and not oms_position_task.done():
            oms_position_task.cancel()
            tasks_to_await.append(oms_position_task)

        try:
            from backend.services.bot_runtime import bot_runtime

            await bot_runtime.shutdown()
        except Exception:
            pass

        try:
            from backend.services.algo_engine import algo_engine

            await algo_engine.shutdown()
        except Exception:
            pass

        if "loop_monitor_task" in locals() and not loop_monitor_task.done():
            loop_monitor_task.cancel()
            tasks_to_await.append(loop_monitor_task)

        push_t = manager.push_task
        if push_t and not push_t.done():
            push_t.cancel()
            tasks_to_await.append(push_t)

        pubsub_t = getattr(manager, "pubsub_task", None)
        if pubsub_t and not pubsub_t.done():
            pubsub_t.cancel()
            tasks_to_await.append(pubsub_t)

        if tasks_to_await:
            await asyncio.gather(*tasks_to_await, return_exceptions=True)
    except Exception as e:
        print(f"⚠️ 取消后台任务时发生异常: {e}")

    try:
        loop = asyncio.get_running_loop()
        executor = getattr(loop, "_default_executor", None)
        if executor:
            executor.shutdown(wait=False)
    except Exception:
        pass

    try:
        if global_llm_client:
            await global_llm_client.close()
        await llm_service.close()
    except Exception as e:
        print(f"⚠️ 关闭 AI 客户端异常: {e}")

    try:
        print("🛑 [Cleanup] 正在排空并关闭 Redis 异步写入队列...")
        await redis_batch_writer.stop()
    except Exception as e:
        print(f"⚠️ 关闭 Redis 队列异常: {e}")

    try:
        print("🧹 [Cleanup] 正在清空 Redis 临时行情缓存...")
        await redis_client.delete("quant:quotes:latest")
    except Exception as e:
        print(f"⚠️ 清理 Redis 缓存异常: {e}")

    try:
        await redis_client.aclose()
    except Exception as e:
        print(f"⚠️ 关闭 Redis 连接池异常: {e}")

    try:
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
