import asyncio
from backend.routers.macro import get_data_center_dashboard
from backend.core.redis_client import redis_client

async def main():
    try:
        await redis_client.delete("macro_dashboard_aggregate")
        result = await get_data_center_dashboard()
        import json
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
