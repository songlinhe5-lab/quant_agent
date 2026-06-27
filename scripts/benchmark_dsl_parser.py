import os
import sys
import time
import json

# 将项目根目录加入 sys.path，以便能够正确识别并导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.screener_service import screener_service

def run_benchmark():
    print("=" * 60)
    print("🚀 开始基准测试：DSL 解析引擎 (ScreenerService.parse_dsl_to_futu_filters)")
    print("=" * 60)

    # 构造一个包含各种复杂类型（百分位、财务比率、累加、技术形态等）的重量级复合 DSL
    test_dsl = json.dumps({
        "dsl_display": "market:hk pe:10~20 mktcap:>10B MACD金叉 RSI超卖",
        "markets": ["HK", "US"],
        "exclude_st": True,
        "technical_patterns": ["macd_gold_cross", "rsi_oversold", "gap_up"],
        "filters": [
            {"field": "PE_TTM", "type": "simple", "min_value": 10.0, "max_value": 20.0},
            {"field": "MARKET_CAP", "type": "simple", "term": "ANNUAL", "min_value": 10000000000.0},
            {"field": "HIST_PERCENTILE_PE", "type": "featured", "max_value": 40.0},
            {"field": "CURRENT_RATIO", "type": "financial", "term": "ANNUAL", "min_value": 200.0},
            {"field": "OPERATING_MARGIN_TTM", "type": "financial", "min_value": 15.0},
            {"field": "PRICE_CHANGE_PCT", "type": "accumulate", "min_value": -0.05, "max_value": 0.05}
        ]
    })

    iterations = 100000
    print(f"📦 测试负载: 单个 DSL 包含 6 个过滤条件 + 3 个技术形态")
    print(f"🔄 循环次数: {iterations:,} 次")

    # 预热 (Warm-up)，让底层的 Pydantic 核心和 Python 解释器完成必要的缓存初始化
    screener_service.parse_dsl_to_futu_filters(test_dsl)

    # 开始高频测速
    start_time = time.perf_counter()
    for _ in range(iterations):
        screener_service.parse_dsl_to_futu_filters(test_dsl)
    end_time = time.perf_counter()

    total_time = end_time - start_time
    ops = iterations / total_time

    print("\n📊 [测试结果]")
    print(f"总耗时:   {total_time:.4f} 秒")
    print(f"吞吐量:   {ops:,.0f} 解析/秒 (OPS)")
    print(f"单次耗时: {(total_time / iterations) * 1000000:.2f} 微秒")
    print("=" * 60)
    print("💡 提示：如果 OPS 能够突破 10,000，说明 Pydantic 模型的内存全局静态化重构非常成功！")

if __name__ == "__main__":
    run_benchmark()