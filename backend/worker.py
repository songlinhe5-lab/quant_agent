import asyncio
import os
import socket
import sys
import uuid
import warnings

from dotenv import load_dotenv

# 过滤多进程产生的警告
warnings.filterwarnings("ignore", module="multiprocessing.resource_tracker")

# 🚨 防御：为底层所有未显式指定 timeout 的同步 Socket 注入 15 秒超时
socket.setdefaulttimeout(15.0)

# 确保当前路径包含项目根目录
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

# 导入核心组件和各种守护进程服务
from backend.core.database import engine  # noqa: E402
from backend.core.redis_client import redis_batch_writer, redis_client  # noqa: E402
from backend.services.finnhub_service import finnhub_service  # noqa: E402
from backend.services.notification_service import notification_service  # noqa: E402
from backend.services.screener_service import screener_service  # noqa: E402
from backend.services.sentiment_tracker import sentiment_tracker  # noqa: E402
from backend.services.ticker_service import ticker_service  # noqa: E402
from backend.services.yfinance_service import yf_service  # noqa: E402
from backend.workers.quote_publisher import QuotePublisher  # noqa: E402

WORKER_UUID = str(uuid.uuid4())


async def worker_heartbeat_daemon() -> None:
    """后台任务：维持集群节点心跳，并动态计算一致性哈希分片排名 (HA 高可用)"""
    while True:
        try:
            # 1. 注册存活心跳 (TTL=15秒)
            heartbeat_key = f"quant:worker:heartbeat:{WORKER_UUID}"
            await redis_client.set(heartbeat_key, "alive", ex=15)

            # 2. 扫描所有存活的 Worker
            cursor = 0
            active_workers = []
            while True:
                cursor, keys = await redis_client.scan(cursor=cursor, match="quant:worker:heartbeat:*", count=100)
                active_workers.extend(keys)
                if cursor == 0:
                    break

            # 3. 对集群所有 UUID 进行字典序排序，计算自己的 Rank
            active_uuids = sorted(
                [k.decode("utf-8").split(":")[-1] if isinstance(k, bytes) else k.split(":")[-1] for k in active_workers]
            )

            if WORKER_UUID in active_uuids:
                new_worker_id = active_uuids.index(WORKER_UUID)
                new_worker_total = len(active_uuids)

                # 💡 动态覆写环境变量，全局任何调用 is_my_shard 的地方
                # 都会瞬间自动转移阵地！
                env_worker_id = os.getenv("WORKER_ID")
                env_worker_total = os.getenv("WORKER_TOTAL")
                if str(new_worker_id) != env_worker_id or str(new_worker_total) != env_worker_total:
                    os.environ["WORKER_ID"] = str(new_worker_id)
                    os.environ["WORKER_TOTAL"] = str(new_worker_total)
                    print(
                        "🔄 [HA 自动容灾] 探测到集群节点变动！"
                        f"当前节点重新定级: Rank {new_worker_id}"
                        f" / Total {new_worker_total}"
                    )
        except Exception:
            pass
        await asyncio.sleep(5)


async def main():
    print("\n=====================================================")
    print("🚀 [Quant Worker] 启动独立数据守护进程 (Data Producer)")
    print("=====================================================\n")

    # 1. 启动全局 Redis 异步高频批量写入队列
    redis_batch_writer.start()

    tasks = []

    # 🚀 0. 启动高可用心跳组网
    tasks.append(asyncio.create_task(worker_heartbeat_daemon()))

    # 🚀 1. 启动行情生产者后台守护任务 (非阻塞)
    publisher = QuotePublisher()
    all_quote_tickers = [
        "US.AAPL",
        "HK.00700",
        "US.TSLA",
        "US.SPY",
        "US.QQQ",
        "US.NVDA",
        "US.MSFT",
        "US.AMZN",
        "US.META",
        "US.GOOGL",
    ]
    tasks.append(
        asyncio.create_task(
            # 💡 这里直接传入所有 ticker，只要 publisher.run_daemon 内部
            # 每次循环调用 is_my_shard 即可实现动态跟随
            publisher.run_daemon(all_quote_tickers, interval=3.0)
        )
    )

    # 🚀 2. 启动本地离线词库后台自动同步任务
    tasks.append(asyncio.create_task(ticker_service.sync_tickers_daemon()))

    # 🚀 3. 启动 YFinance 宏观指标防封控后台守护进程
    tasks.append(asyncio.create_task(yf_service.macro_data_daemon()))

    # 🚀 4. 启动 Finnhub 全局长短链接合并守护进程
    tasks.append(asyncio.create_task(finnhub_service.run_global_daemon()))

    # 🚀 5. 启动情绪风向标长期追踪打点任务
    tasks.append(asyncio.create_task(sentiment_tracker.track_daemon()))

    # 🚀 6. 启动选股器相关的各类定时与订阅后台任务
    tasks.append(asyncio.create_task(screener_service.screener_subscription_daemon()))
    tasks.append(asyncio.create_task(screener_service.daily_market_summary_daemon()))
    tasks.append(asyncio.create_task(screener_service.clean_obsolete_knowledge_base_daemon()))

    print("✅ [Worker] 所有数据拉取与守护任务已成功启动并在后台运行！")
    msg = "✅ [Quant Worker] 独立数据生产节点已成功连线启动！"
    asyncio.create_task(notification_service.send_alert(msg))

    # 挂起主线程，保持守护进程运行
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        print("\n🛑 [Worker] 收到退出信号，正在关闭...")
    finally:
        await redis_batch_writer.stop()
        await redis_client.aclose()
        engine.dispose()
        print("✅ [Worker] 资源已安全释放。")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
