# verify_redis.py
import asyncio
import redis.asyncio as redis
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core.proto.market_pb2 import QuoteData  # type: ignore

async def main():
    load_dotenv()
    redis_password = os.getenv("REDIS_PASSWORD", "quant_redis_secret_2026")
    
    print("🔍 开始诊断量化行情 Redis 数据总线...\n")
    
    # 连接到本地 Redis (关闭 decode_responses 以支持 protobuf 字节流)
    try:
        r = redis.Redis(host='localhost', port=6379, password=redis_password)
        await r.ping()
        print("✅ Redis 连接成功！\n")
    except Exception as e:
        print(f"❌ Redis 连接失败，请检查 Docker 或本地 Redis 是否已启动: {e}")
        return

    # 1. 检查最新快照缓存 (Hash)
    print("=========================================")
    print("📦 1. 检查行情快照缓存 (quant:quotes:latest)")
    print("=========================================")
    cached_data = await r.hgetall("quant:quotes:latest")
    if not cached_data:
        print("⚠️ 缓存为空。请确保前端页面已经打开并发送了订阅请求 (因为后端只拉取前端订阅的标的)。")
    else:
        futu_count = 0
        yf_count = 0
        for ticker_bytes, payload_bytes in cached_data.items():
            ticker = ticker_bytes.decode('utf-8') if isinstance(ticker_bytes, bytes) else str(ticker_bytes)
            quote_msg = QuoteData()
            try:
                quote_msg.ParseFromString(payload_bytes)
                source = quote_msg.source
                if source == 'futu': futu_count += 1
                elif source != 'mock': yf_count += 1
            
                print(f"  • [{ticker:^8}] 最新价: {quote_msg.last_price:<8.2f} | 数据源: {source}")
            except Exception as e:
                print(f"  • [{ticker:^8}] 解析 Protobuf 失败: {e}")
            
        print(f"\n📊 统计: 共 {len(cached_data)} 个标的 (Futu: {futu_count}, YFinance: {yf_count})")

    # 2. 检查实时消息总线 (Pub/Sub)
    print("\n=========================================")
    print("📡 2. 监听实时行情总线 (quant:quotes:stream) 10秒钟...")
    print("=========================================")
    pubsub = r.pubsub()
    await pubsub.subscribe("quant:quotes:stream")
    
    try:
        # 设置 10 秒超时监听
        async with asyncio.timeout(10.0):
            async for msg in pubsub.listen():
                if msg['type'] == 'message':
                    try:
                        quote_msg = QuoteData()
                        quote_msg.ParseFromString(msg['data'])
                        source = quote_msg.source
                        icon = "🔵" if source == "futu" else "🟣"
                        print(f"  {icon} [实时跳动] {quote_msg.ticker}: {quote_msg.last_price} ({quote_msg.change_pct})")
                    except Exception as e:
                        print(f"  ❌ [解析失败] {e}")
    except asyncio.TimeoutError:
        print("\n✅ 监听结束。")
    finally:
        try:
            await pubsub.close()
        finally:
            await r.aclose()

if __name__ == "__main__":
    asyncio.run(main())
