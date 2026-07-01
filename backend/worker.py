import asyncio
import json
import os
import socket
import sys
import time
import uuid
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

WORKER_UUID = str(uuid.uuid4())
NODE_ROLE = os.getenv("NODE_ROLE", "master")
NODE_ID = os.getenv("SLAVE_ID", socket.gethostname())
ENABLED_COLLECTORS = get_enabled_collectors()


async def worker_heartbeat_daemon() -> None:
    """后台任务：维持集群节点心跳，并动态计算一致性哈希分片排名 (HA 高可用)"""
    while True:
        try:
            # 1. 注册存活心跳 (TTL=15秒) - 兼容旧版分片逻辑
            heartbeat_key = f"quant:worker:heartbeat:{WORKER_UUID}"
            await redis_client.set(heartbeat_key, "alive", ex=15)

            # 2. 注册节点能力到 Redis (供 ClusterManager 发现)
            node_key = f"quant:node:{NODE_ID}"
            node_info = {
                "uuid": WORKER_UUID,
                "node_id": NODE_ID,
                "role": NODE_ROLE,
                "host": os.getenv("NODE_HOST", socket.gethostname()),
                "port": int(os.getenv("NODE_PORT", "8000")),
                "collectors": ENABLED_COLLECTORS,
                "started_at": time.time(),
                "status": "healthy",
            }
            await redis_client.set(node_key, json.dumps(node_info), ex=15)

            # 3. 扫描所有存活的 Worker (分片排名)
            cursor = 0
            active_workers = []
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match="quant:worker:heartbeat:*", count=100
                )
                active_workers.extend(keys)
                if cursor == 0:
                    break

            active_uuids = sorted(
                [
                    k.decode("utf-8").split(":")[-1]
                    if isinstance(k, bytes)
                    else k.split(":")[-1]
                    for k in active_workers
                ]
            )

            if WORKER_UUID in active_uuids:
                new_worker_id = active_uuids.index(WORKER_UUID)
                new_worker_total = len(active_uuids)

                env_worker_id = os.getenv("WORKER_ID")
                env_worker_total = os.getenv("WORKER_TOTAL")
                if (
                    str(new_worker_id) != env_worker_id
                    or str(new_worker_total) != env_worker_total
                ):
                    os.environ["WORKER_ID"] = str(new_worker_id)
                    os.environ["WORKER_TOTAL"] = str(new_worker_total)
                    print(
                        f"[HA] cluster changed: Rank {new_worker_id}"
                        f" / Total {new_worker_total}"
                    )
        except Exception:
            pass
        await asyncio.sleep(5)


async def main():
    print("\n=====================================================")
    print(f"  [Quant Worker] Role: {NODE_ROLE} | ID: {NODE_ID}")
    print(f"  Collectors: {ENABLED_COLLECTORS}")
    print("=====================================================\n")

    # 1. 启动 Redis 批量写入队列
    redis_batch_writer.start()

    tasks = []

    # 2. 心跳 + 能力注册 daemon
    tasks.append(asyncio.create_task(worker_heartbeat_daemon()))

    # 3. Master 节点: 启动 ClusterManager 发现从节点
    if NODE_ROLE == "master":
        from backend.workers.cluster_manager import cluster_manager

        await cluster_manager.start()
        print("  [master] ClusterManager started - discovering slave nodes")

    # 4. 按配置启动采集器守护进程
    print("  Starting collector daemons:")
    collector_tasks = await start_collector_daemons(ENABLED_COLLECTORS)
    tasks.extend(collector_tasks)

    # 5. 通用后台任务 (仅 master)
    if NODE_ROLE == "master":
        from backend.services.screener_service import screener_service
        from backend.services.sentiment_tracker import sentiment_tracker

        tasks.append(asyncio.create_task(ticker_service.sync_tickers_daemon()))
        tasks.append(asyncio.create_task(sentiment_tracker.track_daemon()))
        tasks.append(
            asyncio.create_task(screener_service.screener_subscription_daemon())
        )
        tasks.append(
            asyncio.create_task(screener_service.daily_market_summary_daemon())
        )
        tasks.append(
            asyncio.create_task(
                screener_service.clean_obsolete_knowledge_base_daemon()
            )
        )
        print("  [master] core daemons started (ticker/sentiment/screener)")

    print(f"\n  All {len(tasks)} tasks running!")
    asyncio.create_task(
        notification_service.send_alert(
            f"  [Worker {NODE_ID}] role={NODE_ROLE}, "
            f"collectors={ENABLED_COLLECTORS}"
        )
    )

    # 挂起主线程
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        print("\n  [Worker] shutting down...")
    finally:
        # 清理 ClusterManager
        if NODE_ROLE == "master":
            from backend.workers.cluster_manager import cluster_manager

            await cluster_manager.stop()
        await redis_batch_writer.stop()
        await redis_client.aclose()
        engine.dispose()
        print("  [Worker] resources released.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
