import asyncio
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from backend.core.redis_client import redis_client
from backend.services.akshare_service import akshare_service

async def main():
    try:
        print("🔄 正在拉取南向资金数据 (Southbound)...")
        south_data = await akshare_service.get_southbound_flow()
        print(json.dumps(south_data, indent=2, ensure_ascii=False))
        
        print("\n🔄 正在拉取北向资金数据 (Northbound)...")
        north_data = await akshare_service.get_northbound_flow()
        print(json.dumps(north_data, indent=2, ensure_ascii=False))
    finally:
        await redis_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
