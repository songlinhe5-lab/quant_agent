import asyncio
import os
import sys
import argparse
from dotenv import load_dotenv

# 将项目根目录加入 sys.path，避免 ModuleNotFoundError
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.services.futu_service import futu_service
from backend.services.yfinance_service import yf_service
from backend.services.notification_service import notification_service
from backend.services.fred_service import fred_service
from backend.services.llm_service import llm_service
from backend.core.redis_client import redis_client

async def test_yfinance_service():
    print("🟣 [YFinance] 测试雅虎财经数据源... ", end="", flush=True)
    errors = []
    
    success, info, msg = await yf_service.fetch_yf_data("US.AAPL", "info", ttl=60)
    if not success: errors.append(f"获取基本面(info)失败: {msg}")
        
    success, df, msg = await yf_service.fetch_yf_data("HK.00700", "history", ttl=60, period="5d")
    if not success: errors.append(f"获取历史K线(history)失败: {msg}")

    res = await yf_service.get_tech_indicators("US.TSLA", lookback_days=1)
    if res.get("status") != "success": errors.append(f"计算技术指标失败: {res.get('message')}")

    success_es, df_es, msg_es = await yf_service.fetch_yf_data("ES=F", "history", ttl=60, period="1d")
    if not success_es: errors.append(f"获取期货 ES=F 失败: {msg_es}")

    success_cl, df_cl, msg_cl = await yf_service.fetch_yf_data("CL=F", "history", ttl=60, period="1d")
    if not success_cl: errors.append(f"获取期货 CL=F 失败: {msg_cl}")

    success_fx, info_fx, msg_fx = await yf_service.fetch_yf_data("EURUSD=X", "info", ttl=60)
    if not success_fx: errors.append(f"获取外汇 EURUSD=X 失败: {msg_fx}")

    if errors:
        print("❌ 异常 (将自动降级)")
        for err in errors:
            print(f"    - {err}")
    else:
        print("✅ 正常")

async def test_futu_service(close_after: bool = True):
    print("🔵 [Futu] 测试富途 OpenD 接口... ", end="", flush=True)
    errors = []
    
    futu_service.connect()
    if futu_service.status != "CONNECTED":
        errors.append(f"未连接至 OpenD (当前状态: {futu_service.status})")
    else:
        try:
            res = await futu_service.get_quote("HK.00700")
            if res.get("status") != "success": errors.append(f"获取实时快照失败: {res.get('message')}")

            res = await futu_service.get_history("HK.00700", num=10)
            if res.get("status") != "success": errors.append(f"获取历史K线失败: {res.get('message')}")

            res = await futu_service.get_fundamental("HK.00700")
            if res.get("status") != "success": errors.append(f"获取基本面失败: {res.get('message')}")

            res = await futu_service.get_fund_flow("HK.00700")
            if res.get("status") != "success": errors.append(f"获取资金流与席位失败: {res.get('message')}")

            res = await futu_service.get_option_chain("US.AAPL")
            if res.get("status") != "success": errors.append(f"获取期权链失败: {res.get('message')}")

            res = await futu_service.get_account_info("HK")
            if res.get("status") != "success": errors.append(f"获取账户信息失败: {res.get('message')}")
        except Exception as e:
            errors.append(f"API 调用发生未知异常: {e}")

    if close_after:
        futu_service.close()
        
    if errors:
        print("⚠️ 异常 (功能可能受限)")
        for err in errors:
            print(f"    - {err}")
    else:
        print("✅ 正常")

async def test_notification_service():
    print("🔔 [Notify] 测试系统通知与 Redis... ", end="", flush=True)
    errors = []
    try:
        await redis_client.ping()
        await notification_service.send_alert("这是一条来自后端启动自检的通知！")
    except Exception as e:
        errors.append(f"Redis 未连接，无法发送通知: {e}")

    if errors:
        print("❌ 失败")
        for err in errors:
            print(f"    - {err}")
    else:
        print("✅ 正常")

async def test_fred_service():
    print("🏛️  [FRED] 测试圣路易斯联储宏观接口... ", end="", flush=True)
    errors = []
    res = await fred_service.get_series_observations("DGS10", limit=5)
    if res.get("status") != "success" or not res.get("data"):
        errors.append(f"获取宏观数据失败: {res.get('message')}")

    if errors:
        print("❌ 失败")
        for err in errors:
            print(f"    - {err}")
    else:
        print("✅ 正常")

async def main(service: str):
    load_dotenv()
    print(f"🚀 开始对 backend/services 下的接口进行深度自检 (测试范围: {service})...\n")
    
    try:
        if service in ["all", "yfinance"]: await test_yfinance_service()
        if service in ["all", "futu"]: await test_futu_service()
        if service in ["all", "notification"]: await test_notification_service()
        if service in ["all", "fred"]: await test_fred_service()
    finally:
        # 清理全局 Redis 连接池防止报 unclosed resource 警告
        await redis_client.aclose()
        await fred_service.close()
        await llm_service.close()
        yf_service.close()
        
    print("\n🎉 全部服务自检完成！")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="量化后端服务连通性自检脚本")
    parser.add_argument(
        "--service", "-s", type=str, choices=["all", "yfinance", "futu", "notification", "fred"], default="all",
        help="指定要测试的服务: all, yfinance, futu, notification, fred"
    )
    args = parser.parse_args()
    
    asyncio.run(main(args.service))