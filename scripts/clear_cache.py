import asyncio
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
load_dotenv()

from backend.core.redis_client import redis_client

async def clear_all_cache():
    try:
        print("🧹 正在连接 Redis 并发送 FLUSHDB 指令...")
        await redis_client.flushdb()
        print("✅ Redis 缓存已全部清空，你可以重新启动系统了！")
    finally:
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(clear_all_cache())