import asyncio
import sys
import os

# 确保能够找到 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.futu_service import futu_service

async def run_tests():
    print("🚀 开始连接 Futu OpenD 进行高级参数测试...\n")
    
    # 💡 手动触发连接 (独立脚本环境必需)
    futu_service.connect()
    
    # 等待异步网关就绪
    await asyncio.sleep(1.5)
    
    if getattr(futu_service, "status", "CONNECTED") != "CONNECTED":
        print("⚠️ 提示: Futu OpenD 当前未连接，后续操作可能返回失败。请检查网关。")

    try:
        # -------------------------------------------------------------
        # 测试 1: continuous_period (连续满足条件的期数)
        # 场景: 连续 3 年 (ANNUAL=100) ROIC > 15% 的美股印钞机
        # -------------------------------------------------------------
        print("🧪 [Test 1] 正在测试 continuous_period (连续 3 年 ROIC > 15%)...")
        f1 = [
            {"field": "MARKET_CAP", "min": 50000000000}, # 市值大于500亿过滤噪音
            {
                "field": "ROIC", 
                "type": "financial", 
                "term": "ANNUAL",    # 100 代表年度数据
                "min": 0.15,         # 大于 15%
                "continuous_period": 3 # 连续 3 年
            }
        ]
        
        res1 = await futu_service.screen_stocks("US", f1)
        if res1["status"] == "success":
            stocks = res1.get("data", [])
            print(f"✅ 成功筛出 {len(stocks)} 只连续3年ROIC>15%的美股。例如: {[s['symbol'] for s in stocks[:5]]}\n")
        else:
            print(f"❌ Test 1 失败: {res1['message']}\n")

        # -------------------------------------------------------------
        # 测试 2: period_average + duration (区间移动平均)
        # 场景: 过去 5 年 (duration=5)，平均净资产收益率 (ROE) > 20%
        # -------------------------------------------------------------
        print("🧪 [Test 2] 正在测试 period_average + duration (近 5 年平均 ROE > 20%)...")
        f2 = [
            {"field": "MARKET_CAP", "min": 50000000000},
            {
                "field": "ROE", 
                "type": "financial", 
                "term": "ANNUAL",
                "min": 0.20,
                "period_average": True,  # 开启求均值
                "duration": 5            # 过去5年
            }
        ]
        
        res2 = await futu_service.screen_stocks("US", f2)
        if res2["status"] == "success":
            stocks = res2.get("data", [])
            print(f"✅ 成功筛出 {len(stocks)} 只过去5年平均ROE>20%的美股。例如: {[s['symbol'] for s in stocks[:5]]}\n")
        else:
            print(f"❌ Test 2 失败: {res2['message']}\n")

        # -------------------------------------------------------------
        # 测试 3: future_duration (预期前瞻分析)
        # 场景: 华尔街一致预期，未来第 2 年 (future_duration=2) EPS 增长率大于 20%
        # -------------------------------------------------------------
        print("🧪 [Test 3] 正在测试 future_duration (预期未来第2年 EPS 增长率 > 20%)...")
        f3 = [
            {"field": "MARKET_CAP", "min": 10000000000},
            {
                "field": "EPS_GROWTH_RATE", 
                "type": "financial", 
                "term": "ANNUAL",
                "min": 0.20,
                "future_duration": 2  # FY2
            }
        ]
        
        res3 = await futu_service.screen_stocks("US", f3)
        if res3["status"] == "success":
            stocks = res3.get("data", [])
            print(f"✅ 成功筛出 {len(stocks)} 只华尔街预期两年后EPS暴增的标的。例如: {[s['symbol'] for s in stocks[:5]]}\n")
        else:
            print(f"❌ Test 3 失败: {res3['message']}\n")
            
        # -------------------------------------------------------------
        # 测试 4: unit + lower/upper_included (严格边界与单位控制)
        # 场景: 净利润恰好等于或大于某数值 (控制是否包含下限)
        # -------------------------------------------------------------
        print("🧪 [Test 4] 正在测试 unit 与包含边界 (剔除等于下界的值)...")
        f4 = [
            {"field": "MARKET_CAP", "min": 10000000000},
            {
                "field": "NET_PROFIT", 
                "type": "financial", 
                "term": "ANNUAL",
                "min": 50000000, 
                "lower_included": False, # 不包含等于 50,000,000 的情况 (严格大于)
                "unit": 1 # 1=原生单位。不让引擎擅自按万/亿进行缩放计算
            }
        ]
        
        res4 = await futu_service.screen_stocks("US", f4)
        if res4["status"] == "success":
            stocks = res4.get("data", [])
            print(f"✅ 边界测试通过。筛出 {len(stocks)} 只标的。\n")
        else:
            print(f"❌ Test 4 失败: {res4['message']}\n")

    finally:
        print("🏁 测试结束，断开 OpenD 连接。")
        if hasattr(futu_service, 'close'):
            futu_service.close()
        elif hasattr(futu_service, 'conn_mgr') and hasattr(futu_service.conn_mgr, 'close'):
            futu_service.conn_mgr.close()

if __name__ == "__main__":
    asyncio.run(run_tests())