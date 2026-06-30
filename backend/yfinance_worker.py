"""
==========================================
🌏 YFinance 独立数据采集节点 (Standalone Worker)
==========================================
轻量级守护进程，仅运行 YFinance 宏观数据拉取任务。
适用于部署在海外多 VPS 节点，利用分布式锁实现 HA 冗余。

启动方式:
  python backend/yfinance_worker.py

依赖:
  - Redis (REDIS_HOST / REDIS_PORT / REDIS_PASSWORD)
  - yfinance 库
"""

import asyncio
import os
import socket
import sys
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

WORKER_UUID = str(uuid.uuid4())
NODE_ROLE = os.getenv("NODE_ROLE", "yfinance")


async def heartbeat_daemon() -> None:
    """后台心跳：在 Redis 中注册存活状态，支持集群发现"""
    from backend.core.redis_client import redis_client

    while True:
        try:
            heartbeat_key = f"quant:yfinance:heartbeat:{WORKER_UUID}"
            await redis_client.set(heartbeat_key, "alive", ex=15)
        except Exception:
            pass
        await asyncio.sleep(5)


async def main():
    from backend.core.redis_client import redis_batch_writer, redis_client
    from backend.services.notification_service import notification_service
    from backend.services.yfinance_service import yf_service

    print("\n=====================================================")
    print("🌏 [YFinance Worker] 独立数据采集节点启动")
    print(f"   UUID: {WORKER_UUID}")
    print(f"   Role: {NODE_ROLE}")
    print("=====================================================\n")

    # 启动 Redis 异步批量写入队列
    redis_batch_writer.start()

    tasks = []

    # 1. 心跳守护
    tasks.append(asyncio.create_task(heartbeat_daemon()))

    # 2. YFinance 宏观数据守护 (核心任务)
    #    内置分布式锁，多节点同时运行只有一个实际执行拉取
    tasks.append(asyncio.create_task(yf_service.macro_data_daemon()))

    print("✅ [YFinance Worker] 数据采集守护任务已启动！")
    asyncio.create_task(
        notification_service.send_alert(
            f"✅ [YFinance Worker {WORKER_UUID[:8]}] 独立数据采集节点已上线"
        )
    )

    # 挂起主线程
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        print("\n🛑 [YFinance Worker] 收到退出信号，正在关闭...")
    finally:
        await redis_batch_writer.stop()
        await redis_client.aclose()
        print("✅ [YFinance Worker] 资源已安全释放。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
