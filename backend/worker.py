import asyncio
import os
import socket
import sys
import warnings

from dotenv import load_dotenv

# 过滤多进程产生的警告
warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")

# 防御：为底层所有未显式指定 timeout 的同步 Socket 注入 15 秒超时
socket.setdefaulttimeout(15.0)

# 确保当前路径包含项目根目录
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

# 导入核心组件
from backend.core.database import engine  # noqa: E402
from backend.core.redis_client import redis_batch_writer, redis_client  # noqa: E402
from backend.services.notification_service import notification_service  # noqa: E402
from backend.services.ticker_service import ticker_service  # noqa: E402
from backend.workers.collector_registry import (  # noqa: E402
    get_enabled_collectors,
    start_collector_daemons,
)

ENABLED_COLLECTORS = get_enabled_collectors()
IS_DATA_NODE = os.getenv("DATA_NODE", "false").lower() == "true"


async def main():
    node_role = "数据节点 (Data Node)" if IS_DATA_NODE else "主节点 (Master)"
    print("\n=====================================================")
    print(f"  [Quant Worker] Role: {node_role}")
    print(f"  [Quant Worker] Collectors: {ENABLED_COLLECTORS}")
    print("=====================================================\n")

    # 1. 启动 Redis 批量写入队列
    redis_batch_writer.start()

    tasks = []

    # 2. 按配置启动采集器守护进程
    print("  Starting collector daemons:")
    collector_tasks = await start_collector_daemons(ENABLED_COLLECTORS)
    tasks.extend(collector_tasks)

    # 3. 后台服务任务 (数据节点不需要 DB 依赖的核心服务)
    if not IS_DATA_NODE:
        from backend.services.screener_service import screener_service
        from backend.services.sentiment_tracker import sentiment_tracker

        tasks.append(asyncio.create_task(ticker_service.sync_tickers_daemon()))
        tasks.append(asyncio.create_task(sentiment_tracker.track_daemon()))
        tasks.append(asyncio.create_task(screener_service.screener_subscription_daemon()))
        tasks.append(asyncio.create_task(screener_service.daily_market_summary_daemon()))
        tasks.append(asyncio.create_task(screener_service.clean_obsolete_knowledge_base_daemon()))
        print("  Core daemons started (ticker/sentiment/screener)")
    else:
        print("  [Data Node] 跳过 DB 依赖服务 (ticker/sentiment/screener)")

    print(f"\n  All {len(tasks)} tasks running!")
    asyncio.create_task(notification_service.send_alert(f"[Worker] role={node_role} collectors={ENABLED_COLLECTORS}"))

    # 挂起主线程
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        print("\n  [Worker] shutting down...")
    finally:
        await redis_batch_writer.stop()
        await redis_client.aclose()
        engine.dispose()
        print("  [Worker] resources released.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
