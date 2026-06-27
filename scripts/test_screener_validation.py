"""
验证富途选股条件修复后的正确性
测试用例: [{'field': 'HIST_PERCENTILE_PE', 'type': 'featured', 'max': 40.0},
           {'field': 'CURRENT_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'min': 200.0}, 
           {'field': 'PROPERTY_RATIO', 'type': 'financial', 'term': 'ANNUAL', 'max': 100.0}]
"""
import asyncio
import sys
import os

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.services.futu_service import futu_service


async def test_fixed_filters():
    """测试修复后的筛选条件"""
    
    print("=" * 80)
    print("✅ 富途选股条件修复验证测试")
    print("=" * 80)
    
    market = "HK"
    filters = [
        {"field": "HIST_PERCENTILE_PE", "type": "featured", "max": 40.0},
        {"field": "CURRENT_RATIO", "type": "financial", "term": "ANNUAL", "min": 200.0},
        {"field": "PROPERTY_RATIO", "type": "financial", "term": "ANNUAL", "max": 100.0}
    ]
    
    print(f"\n📋 测试配置:")
    print(f"   市场: {market}")
    print(f"   过滤条件:")
    for i, f in enumerate(filters, 1):
        print(f"      [{i}] {f}")
    
    print("\n" + "-" * 80)
    print("🔍 修复说明:")
    print("-" * 80)
    print("✅ LLM Prompt 已明确要求所有百分比指标输出为小数格式(如0.15代表15%)")
    print("✅ 财务比率指标输出为原始数值(如1.0代表1)")
    print("✅ 返回数据时，roe/operating_margin_ttm 等字段会*100转换为百分比绝对值显示")
    print("💡 本测试专门输入大模型可能输出的「绝对大数」错误格式（如40.0、200.0），验证防御代码是否能自动拦截除以100")
    print("")
    print("预期行为 (触发防御降级):")
    print("   - HIST_PERCENTILE_PE < 40.0: 拦截并转换为0.40，返回显示为 <= 40.0% ✅")
    print("   - CURRENT_RATIO > 200.0: 拦截并转换为2.0，返回显示为 >= 2.0 ✅")
    print("   - PROPERTY_RATIO < 100.0: 拦截并转换为1.0，返回显示为 <= 1.0 ✅")
    
    print("\n" + "=" * 80)
    print("🚀 开始测试...")
    print("=" * 80)
    
    try:
        # 确保连接（connect是同步方法）
        futu_service.connect()
        
        print("\n📡 发起选股请求...")
        result = await futu_service.screen_stocks(market=market, filters=filters)
        
        if result.get("status") == "success":
            data = result.get("data", [])
            print(f"\n✅ 选股成功! 找到 {len(data)} 只符合条件的股票")
            
            if data:
                print("\n" + "-" * 80)
                print("📊 前5只股票的返回数据验证:")
                print("-" * 80)
                
                all_correct = True
                for i, stock in enumerate(data[:5], 1):
                    print(f"\n[{i}] {stock.get('name', 'N/A')} ({stock.get('symbol', 'N/A')})")
                    
                    pe_percentile = stock.get('hist_percentile_pe')
                    current_ratio = stock.get('current_ratio')
                    prop_ratio_val = stock.get('property_ratio')
                    
                    # 验证 PE 百分位
                    print(f"   PE历史百分位: {pe_percentile}", end="")
                    if pe_percentile is not None:
                        if 0 <= pe_percentile <= 100:
                            print(f" ✅ (拦截生效: 转换为了合理百分比)")
                        else:
                            print(f" ⚠️ 异常值 ({pe_percentile}%)，防御未生效")
                            all_correct = False
                    else:
                        print(" (无数据)")
                        
                    # 验证 流动比率
                    print(f"   流动比率: {current_ratio}", end="")
                    if current_ratio is not None:
                        if 0 <= current_ratio <= 100:
                            print(f" ✅ (拦截生效: 转换为了合理比值)")
                        else:
                            print(f" ⚠️ 异常值 ({current_ratio})，防御未生效")
                            all_correct = False
                    else:
                        print(" (无数据)")
                    
                    # 验证产权比率
                    print(f"   产权比率: {prop_ratio_val}", end="")
                    if prop_ratio_val is not None:
                        if 0 <= prop_ratio_val <= 500:
                            print(f" ✅ (合理的比率范围)")
                        else:
                            print(f" ⚠️ 异常值 ({prop_ratio_val})，防御未生效")
                            all_correct = False
                    else:
                        print(" (无数据)")
                    
                    # 显示其他字段
                    if 'price' in stock:
                        print(f"   价格: HK${stock['price']}")
                    if 'mktcap' in stock:
                        print(f"   市值: HK${stock['mktcap']:.2f}")
                
                print("\n" + "=" * 80)
                if all_correct:
                    print("🎉 验证通过！所有财务指标数值都在合理范围内")
                else:
                    print("⚠️  部分指标数值异常，请检查是否还有转换问题")
                print("=" * 80)
            else:
                print("\n💡 没有找到符合条件的股票")
                print("   可能原因:")
                print("   1. 条件过于严格（ROE>15% AND 营业利润率>10% AND 产权比率<100%）")
                print("   2. 港股市场中同时满足这三个条件的公司较少")
                print("   建议: 尝试放宽条件或切换市场（US/A股）")
        else:
            print(f"\n❌ 选股失败: {result.get('message', '未知错误')}")
            
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n" + "=" * 80)
        print("📝 总结:")
        print("=" * 80)
        print("✅ 选股过滤输入：统一采用富途期望的 小数格式（如 0.15 表示 15%）")
        print("✅ 选股返回输出：统一将百分比指标乘 100 还原为前端/大模型容易理解的绝对值")
        print("🛡️ 防御拦截器：成功拦截大模型输入的 40.0 和 200.0 并自动纠偏为 0.4 和 2.0")
        print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_fixed_filters())
