"""
应用生命周期管理器 (Startup / Shutdown)
从 main.py 迁出 (ARCH-01)
"""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from backend.core import models
from backend.core.database import AsyncSessionLocal, SessionLocal, async_engine, engine
from backend.core.redis_client import redis_client
from backend.core.security import get_password_hash, verify_password
from backend.services.ai_narrator.llm_service import llm_service
from backend.services.alert.notification import notification_service
from backend.services.macro.fred_service import fred_service
from backend.services.market_engine import manager
from backend.workers.monitor.system_monitor import system_monitor_service

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
    log = structlog.get_logger("quant_agent")

    # === 启动阶段 (Startup) ===
    log.info("\n🚀 [Startup] 正在执行后端核心服务深度自检...")

    # 全局限制 asyncio 与 AnyIO 的最大物理线程池容量，防止 OOM
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="GlobalAsyncioWorker")
        loop.set_default_executor(executor)

        from anyio.to_thread import current_default_thread_limiter

        limiter = current_default_thread_limiter()
        limiter.total_tokens = 64
        log.info("✅ [System] 全局物理线程池容量已安全限制为最大 64 个。")
    except Exception as e:
        log.warning(f"⚠️ [System] 配置全局线程池失败: {e}")

    # 0. 数据源适配器统一注册（BE-ARCH-04: Facade 经 Registry 选源，必须启动时注册）
    log.info("🚀 [Startup] 正在注册数据源适配器...")
    try:
        from backend.services.datasource.adapters import ensure_all_datasources_registered

        registered = ensure_all_datasources_registered()
        log.info(f"✅ [Startup] 数据源适配器注册完成: {registered}")
    except Exception as e:
        log.warning(f"⚠️ [Startup] 数据源适配器注册失败 (部分源可能不可用): {e}")

    # 0.1 初始化默认系统管理员账号
    log.info("🚀 [Startup] 正在初始化系统默认账号...")
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
                log.info("✅ [Startup] 默认管理员账号 (admin/admin) 初始化成功！")
            else:
                # 诊断增强: 区分"已存在"与"密码不匹配"
                if not verify_password("admin", admin.hashed_password):
                    log.warning(
                        "⚠️ [Startup] admin 账号已存在但密码与默认 (admin) 不匹配。"
                        "若登录 401, 请设 FORCE_RESET_ADMIN=true 重启以重置默认密码。"
                    )
                    if os.getenv("FORCE_RESET_ADMIN", "false").lower() == "true":
                        admin.hashed_password = get_password_hash("admin")
                        db.commit()
                        log.info("✅ [Startup] FORCE_RESET_ADMIN=true, 已重置 admin 密码为默认 (admin)")
                else:
                    log.info("✅ [Startup] 默认管理员账号 (admin) 已存在, 跳过初始化。")
    except Exception as e:
        log.error(f"❌ [Startup] 管理员账号初始化失败 (DB 可能未就绪): {e}")

    # 容灾包裹：防止外部 API 不通导致容器死循环无法启动
    # 注 (Phase 3, 2026-08-06)：主服务不再持有/启动 Futu OpenD 实例。
    # OpenD 唯一运行在 data_subservice 节点（DS_CAPABILITIES=futu），
    # 主服务经 DataSourceRouter (DATASOURCE_FUTU_MODE=external) 走 HTTP 调子服务。
    try:
        # 3. Redis 连通性与系统通知测试
        if test_notification_service is not None:
            await asyncio.wait_for(test_notification_service(), timeout=10.0)
        # 4. FRED 宏观数据接口测试
        if test_fred_service is not None:
            await asyncio.wait_for(test_fred_service(), timeout=10.0)
    except asyncio.TimeoutError:
        log.warning("⚠️ [Startup] 核心外部服务预检超时 (10s)，已自动降级跳过")
    except Exception as e:
        log.warning(f"⚠️ [Startup] 核心外部服务连通性预检失败: {e}")

    log.info("\n🎉 [Startup] 所有后端服务自检完成，API 网关启动就绪！\n")

    # 🧠 [Agent] 初始化 AI 主脑相关服务
    log.info("🛠️  [Agent Startup] 装载量化 Tools 沙箱网络客户端...")
    from hermes_agent.tool_registry import ToolRegistry

    global_registry = ToolRegistry()
    log.info(f"✅ [Agent Startup] 成功挂载 {len(global_registry.tools)} 个 AI Agent 核心工具！")

    log.info("🔌 [Agent Startup] 初始化全局共享的大模型连接池...")
    from openai import AsyncOpenAI

    llm_api_key = os.getenv("LLM_API_KEY", "")
    if llm_api_key:
        global_llm_client = AsyncOpenAI(
            api_key=llm_api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        )
        log.info("✅ [Agent Startup] LLM 连接池已初始化")
    else:
        global_llm_client = None
        log.warning("⚠️ [Agent Startup] LLM_API_KEY 未配置，跳过 LLM 客户端初始化")

    # 🚀 启动事件循环健康监控探针
    loop_monitor_task = asyncio.create_task(system_monitor_service.event_loop_monitor_daemon())

    await manager.start_background_tasks()

    asyncio.create_task(notification_service.send_alert("✅ [Quant Agent] 量化引擎数据网关已成功连接并启动！"))

    # 🚀 NAV 快照守护进程 (每 5 分钟)
    async def _nav_snapshot_daemon():
        from backend.services.datasource.router import data_source_router

        while True:
            try:
                hk_acc, us_acc = await asyncio.gather(
                    data_source_router.fetch_futu("ACCOUNT_INFO", market="HK"),
                    data_source_router.fetch_futu("ACCOUNT_INFO", market="US"),
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
                                log.warning(f"[NAV Daemon] DB 写入失败 ({market}): {db_err}")
            except Exception as e:
                log.warning(f"[NAV Daemon] 快照记录失败: {e}")
            await asyncio.sleep(300)

    nav_snapshot_task = asyncio.create_task(_nav_snapshot_daemon())
    log.info("✅ [Startup] NAV 快照守护进程已启动 (每 5 分钟)")

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
                log.warning(f"[OMS Position Daemon] 同步失败: {e}")
            await asyncio.sleep(30)

    oms_position_task = asyncio.create_task(_oms_position_sync_daemon())
    log.info("✅ [Startup] OMS 持仓同步守护进程已启动 (每 30 秒)")

    # 🚀 BotRuntimeManager 恢复
    from backend.workers.oms.bot_runtime import bot_runtime

    try:
        restored = await bot_runtime.restore_bots_from_redis()
        log.info(f"✅ [Startup] BotRuntimeManager 已启动 (恢复 {restored} 个 Bot)")
    except Exception as e:
        log.warning(f"[Startup] BotRuntimeManager 恢复失败: {e}")

    # 🚀 AlgoEngine 恢复
    from backend.workers.oms.algo_engine import algo_engine

    try:
        algo_restored = await algo_engine.restore_from_redis()
        log.info(f"✅ [Startup] AlgoEngine 已启动 (恢复 {algo_restored} 个算法订单)")
    except Exception as e:
        log.warning(f"[Startup] AlgoEngine 恢复失败: {e}")

    # 🚀 MarketEngine broadcast_loop
    try:
        await manager.start_background_tasks()
        log.info("✅ [Startup] MarketEngine broadcast_loop 已启动")
    except Exception as e:
        log.warning(f"[Startup] MarketEngine 启动失败: {e}")

    # 🚀 Finnhub WS 实时 tick 回灌（BE-ARCH-07: 经推送平面统一入口）
    # 仅当配置了 FINNHUB_WS_SYMBOLS 时启动；从节点不跑（外部 WS 收口在 data_subservice）
    try:
        from backend.services.datasource.subscription import subscription_service

        _ws_symbols = [s.strip().upper() for s in os.getenv("FINNHUB_WS_SYMBOLS", "").split(",") if s.strip()]
        tick_ingest_task = subscription_service.start_ingest(_ws_symbols)
        if tick_ingest_task is not None:
            log.info(f"✅ [Startup] Finnhub WS tick 回灌已启动 (订阅 {len(_ws_symbols)} 只标的)")
        else:
            log.info("ℹ️ [Startup] 未配置 FINNHUB_WS_SYMBOLS，跳过 WS tick 回灌")
    except Exception as e:
        log.warning(f"[Startup] Finnhub WS tick 回灌启动失败: {e}")

    # 🚀 FMP 盘后批量财报缓存守护（fmp_collector_daemon）：
    # 业务编排（watchlist 热重载 / 盘后调度 / 通知告警）留在主服务；
    # 数据源连接层（FMPService REST + credit 配额/连接保障）经 DataSourceRouter HTTP 下沉子服务。
    # 主服务只负责"决定拉哪些标的 + 何时拉"，实际 REST 与 credit 计数在子服务完成。
    try:
        from backend.workers.collectors.fmp import fmp_collector_daemon

        # FMP 守护默认全开（数据源能力默认开启，失效在监控显示，不静默禁用）。
        asyncio.create_task(fmp_collector_daemon())
        log.info("✅ [Startup] FMP 盘后批量守护已启动（业务编排留主服务，REST 经子服务）")
    except Exception as e:
        log.warning(f"⚠️ [Startup] FMP 守护启动失败: {e}")

    # 🚀 RL-11 限流告警后台消费器 (异步队列，解耦限流回调与飞书推送 IO)
    try:
        from backend.services.datasource.alert_monitor import rate_limit_alert_monitor

        await rate_limit_alert_monitor.start()
        log.info("✅ [Startup] 限流告警后台消费器已启动")
    except Exception as e:
        # 升级为 error：告警消费器启动失败属可观测性盲区，必须显式暴露
        # （health_deep 的 components.alert_queue 会据此返回 unhealthy）
        log.error(f"[Startup] 限流告警消费器启动失败: {e}")

    yield  # 挂起，FastAPI 正式对外提供服务

    # === 销毁阶段 (Shutdown) ===
    log.info("🛑 正在关闭后端服务，释放资源...")

    shutdown_timer = {"start": time.time()}
    shutdown_steps = []  # 追踪各步骤耗时

    def log_step(name):
        elapsed = time.time() - shutdown_timer["start"]
        shutdown_steps.append(f"{name}: {elapsed:.2f}s")
        log.info(f"[Shutdown Timeline] {name}: {elapsed:.2f}s")

    try:
        tasks_to_await = []

        if "nav_snapshot_task" in locals() and not nav_snapshot_task.done():
            nav_snapshot_task.cancel()
            tasks_to_await.append(nav_snapshot_task)

        if "oms_position_task" in locals() and not oms_position_task.done():
            oms_position_task.cancel()
            tasks_to_await.append(oms_position_task)

        try:
            from backend.workers.oms.bot_runtime import bot_runtime

            await bot_runtime.shutdown()
        except Exception:
            pass

        try:
            from backend.workers.oms.algo_engine import algo_engine

            await algo_engine.shutdown()
        except Exception:
            pass

        if "loop_monitor_task" in locals() and not loop_monitor_task.done():
            loop_monitor_task.cancel()
            tasks_to_await.append(loop_monitor_task)

        # Finnhub WS tick 回灌任务优雅取消
        if "tick_ingest_task" in locals() and tick_ingest_task is not None and not tick_ingest_task.done():
            tick_ingest_task.cancel()
            tasks_to_await.append(tick_ingest_task)

        # RL-11: 停止限流告警后台消费器 (cancel + await 自身 task)
        try:
            from backend.services.datasource.alert_monitor import rate_limit_alert_monitor

            await rate_limit_alert_monitor.stop()
        except Exception:
            pass

        push_t = manager.push_task
        if push_t and not push_t.done():
            push_t.cancel()
            tasks_to_await.append(push_t)

        pubsub_t = getattr(manager, "pubsub_task", None)
        if pubsub_t and not pubsub_t.done():
            pubsub_t.cancel()
            tasks_to_await.append(pubsub_t)

        # ARCH-03: 增加全局超时保护（防止 task 无法响应 cancel）
        if tasks_to_await:
            try:
                log.info(f"🛑 [Shutdown] 等待 {len(tasks_to_await)} 个任务完成...")
                await asyncio.wait_for(
                    asyncio.gather(*tasks_to_await, return_exceptions=True),
                    timeout=30.0,  # ARCH-03: in-flight 任务最大等待 30s
                )
                log.info("✅ [Shutdown] 所有后台任务已优雅取消")
            except asyncio.TimeoutError:
                log.warning("⚠️ [Shutdown] Task 取消超时 (30s)，强制退出")
    except Exception as e:
        log.warning(f"⚠️ 取消后台任务时发生异常: {e}")

    try:
        loop = asyncio.get_running_loop()
        executor = getattr(loop, "_default_executor", None)
        if executor:
            # ARCH-03: 优雅关闭线程池（等待在途任务完成，最多 10s）
            executor.shutdown(wait=True, timeout=10)
    except Exception:
        pass

    try:
        if global_llm_client:
            await global_llm_client.close()
        await llm_service.close()
    except Exception as e:
        log.warning(f"⚠️ 关闭 AI 客户端异常: {e}")

    try:
        # ARCH-03: Redis 批量队列优雅关闭
        log.info("🛑 [Cleanup] 正在排空并关闭 Redis 异步写入队列...")
        from backend.core.redis_client import redis_batch_writer

        success = await redis_batch_writer.stop(timeout_s=15.0)
        if not success:
            log.warning("⚠️ Redis 批量队列关闭不完全")
    except Exception as e:
        log.warning(f"⚠️ 关闭 Redis 队列异常：{e}")

    try:
        log.info("🧹 [Cleanup] 正在清空 Redis 临时行情缓存...")
        await redis_client.delete("quant:quotes:latest")
    except Exception as e:
        log.warning(f"⚠️ 清理 Redis 缓存异常: {e}")

    try:
        await redis_client.aclose()
    except Exception as e:
        log.warning(f"⚠️ 关闭 Redis 连接池异常: {e}")

    try:
        # 注意：backend 不再本地运行 yfinance（已全量外移至 US-YF-A/B 子服务），
        # 故无需在此 close 本地 yf_service。

        # FutuService 为同步 close()，包裹在 to_thread 避免阻塞事件循环
        from backend.services.futu import futu_service

        await asyncio.to_thread(futu_service.close)
    except Exception as e:
        log.warning(f"⚠️ 关闭数据源资源异常：{e}")

    try:
        log.info("🛑 [Cleanup] 正在关闭外部 API 长连接...")
        await fred_service.close()
    except Exception as e:
        log.warning(f"⚠️ 关闭 FRED 等 HTTP 连接池异常: {e}")

    try:
        log.info("🛑 [Cleanup] 正在关闭数据库连接池...")
        engine.dispose()
        await async_engine.dispose()
    except Exception as e:
        log.warning(f"⚠️ 关闭数据库连接池异常：{e}")

    # ARCH-03: 记录 Shutdown 总耗时
    total_time = time.time() - shutdown_timer["start"]
    log_step(f"Total shutdown time: {total_time:.2f}s")
    log.info(f"📊 [Shutdown Summary] Total time: {total_time:.2f}s | Steps: {len(shutdown_steps)}")
