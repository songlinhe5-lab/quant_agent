"""
高级时序选股参数边界测试用例
运行方式: python -m scripts.test_futu_advanced_params
"""
import asyncio
import json

class MockScreenerRequest:
    """模拟您的底层 Futu OpenD 请求装配器"""
    def __init__(self):
        self.financial_filters = []
        
    def add_financial_property(self, name, term=None, year=None,
                               lower=None, upper=None,
                               lower_included=True, upper_included=True,
                               duration=None, continuous_period=None,
                               period_average=None, future_duration=None, unit=None):
        """装配条件并落盘"""
        prop = {
            "field": name,
            "term": term,
            "range": {
                "min": lower, 
                "max": upper,
                "min_included": lower_included,
                "max_included": upper_included
            },
            "logic": {
                "duration": duration,
                "continuous_period": continuous_period,
                "period_average": period_average,
                "future_duration": future_duration
            },
            "unit": unit
        }
        # 剔除空值方便查看
        prop["logic"] = {k: v for k, v in prop["logic"].items() if v is not None}
        self.financial_filters.append(prop)
        print(f"🔧 成功装配底层指令: [字段={name}, 范围={lower}~{upper}, 连续期数={continuous_period or 'N/A'}]")


async def run_tests():
    req = MockScreenerRequest()
    print("🚀 === 测试 1: 连续 N 期稳定增长 ===")
    # 模拟需求：ROIC 同比增长率连续 3 年严格大于 0
    req.add_financial_property(
        name="ROIC_GROWTH_RATE",
        term="ANNUAL",
        lower=0.0,
        lower_included=False,   # 严格大于，不含 0
        continuous_period=3     # 核心参数：连续 3 年
    )
    
    print("\n🚀 === 测试 2: 长期均值回归过滤 ===")
    # 模拟需求：过去 5 年的平均毛利率大于 40%
    req.add_financial_property(
        name="GROSS_PROFIT_RATIO",
        term="ANNUAL",
        lower=0.40,
        period_average=True,    # 核心参数：按均值计算
        duration=5              # 核心参数：过去 5 年窗口
    )
    
    print("\n🚀 === 测试 3: 单位自适应大市值 ===")
    # 模拟需求：市值大于 1000 亿
    req.add_financial_property(
        name="MARKET_CAP",
        lower=1000,
        unit=100000000          # 1亿，即 1000 * 1亿 = 1000亿
    )
    
    print("\n✅ 生成的最终底层通信负载 (Payload):")
    print(json.dumps(req.financial_filters, indent=2, ensure_ascii=False))
    
    # 此处在实盘代码中会调用类似：
    # response = await futu_api_client.request_stock_screen(req)
    # assert response.status == 'ok'

if __name__ == "__main__":
    asyncio.run(run_tests())