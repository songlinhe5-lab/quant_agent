import asyncio
import json
import os
import websockets
from dotenv import load_dotenv

load_dotenv()

async def main():
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("🚨 未找到 FINNHUB_API_KEY，请检查 .env 文件配置。")
        return
        
    uri = f"wss://ws.finnhub.io?token={api_key}"
    print(f"🔗 正在连接 Finnhub WebSocket: {uri.split('token=')[0]}token=***")
    
    try:
        async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
            print("✅ 连接成功！")
            
            # 发送一些热门标的的订阅指令 (测试长链接是否有对应的新闻下发)
            test_symbols = ["0772.HK", "0700.HK", "AAPL", "MSFT"]
            for symbol in test_symbols:
                subscribe_msg = {"type": "subscribe", "symbol": symbol}
                await ws.send(json.dumps(subscribe_msg))
                
                subscribe_msg = {"type": "subscribe-news", "symbol": symbol}
                await ws.send(json.dumps(subscribe_msg))
                
                
                subscribe_msg = {"type": "subscribe-pr", "symbol": symbol}
                await ws.send(json.dumps(subscribe_msg))
                print(f"📡 已订阅行情与新闻流: {symbol}")
                
            print("⏳ 正在监听数据流，请等待 (按 Ctrl+C 退出)...\n")
            
            while True:
                try:
                    # 设置超时，防止一直阻塞没有输出，顺便当个心跳探针
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    data = json.loads(msg)
                    msg_type = data.get("type")
                    
                    if msg_type == "news":
                        print(f"\n🎉 [Premium] 成功收到实时新闻 (News)，共 {len(data.get('data', []))} 条:")
                        print(json.dumps(data, indent=2, ensure_ascii=False))
                    elif msg_type == "trade":
                        trades = data.get("data", [])
                        print(f"📉 收到逐笔交易 (Trade): {len(trades)} 笔 -> {trades[0].get('s')} @ {trades[0].get('p')}")
                    elif msg_type == "ping":
                        pass # 忽略底层自动处理的 ping
                except asyncio.TimeoutError:
                    print("💤 10秒内未收到新数据，连接保持中...")
                    
    except Exception as e:
        print(f"❌ 连接发生异常: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 测试已手动终止。")