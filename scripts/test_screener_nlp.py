"""
独立测试脚本：专门用于验证 ScreenerService 的自然语言意图解析与 RAG 召回能力。
执行方式: python scripts/test_screener_nlp.py
"""
import os
import sys
import asyncio
import json

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from backend.services.screener_service import screener_service

async def test_nlp_parsing():
    # 精选的高难度测试用例集
    test_queries = [
        # 1. 基础指标与百分位（测试基础 LLM 识别）
        "帮我找市值大于 100 亿，且 PE历史百分位 极度低估（小于 20%）的港股。",
        
        # 2. 纯语义/黑话指标（测试 RAG 向量检索召回能力）
        "寻找那些产品溢价能力极强（大于 40%），且手头现金流非常充裕（大于 10 亿）的美股。",
        
        # 3. 行业板块剔除（测试自定义的 exclude_plate 类型解析）
        "找市值大于 50 亿的美股，ROE大于15%，绝对不要金融股，规避地产。",
        
        # 4. 复杂技术形态混合（测试技术指标字符串映射）
        "A股市值超百亿，且今日出现MACD金叉和RSI超卖的科技股"
    ]

    print("=" * 80)
    print("🧠 Screener NLP 意图解析独立测试")
    print("=" * 80)

    for i, query in enumerate(test_queries, 1):
        print(f"\n\033[96m[{i}] 测试输入:\033[0m {query}")
        print("-" * 60)
        
        try:
            # 1. 调用转译服务 (包含 RAG 检索与 LLM 调用)
            dsl_json_str = await screener_service.translate_nlp_to_dsl(query)
            parsed_dsl = json.loads(dsl_json_str)
            
            print("\n\033[92m✅ [LLM 输出 DSL]:\033[0m")
            print(json.dumps(parsed_dsl, indent=2, ensure_ascii=False))
            
            # 2. 验证生成的 DSL 是否能完美通过 Pydantic 校验并转化为 Futu 协议
            markets, futu_filters, post_filters = screener_service.parse_dsl_to_futu_filters(dsl_json_str)
            
            print("\n\033[93m⚙️ [Futu API 底层解析状态]:\033[0m")
            print(f"   - 目标市场: {markets}")
            print(f"   - API 过滤条件: {futu_filters}")
            print(f"   - 内存二次过滤: {post_filters}")
            
        except Exception as e:
            print(f"\n\033[91m❌ [解析失败]:\033[0m {e}")
        print("=" * 80)

if __name__ == "__main__":
    asyncio.run(test_nlp_parsing())