"""
富途底层接口 get_stock_screen 纯粹性诊断脚本
重点测试: add_financial_property 4110 (ROE) 是否生效，以及返回数据是否正确。
执行方式: python scripts/test_futu_screen_direct.py
"""
import os
import sys
import json

# 引入富途官方 SDK 原生库
from futu import (
    OpenQuoteContext, StockScreenRequest, ScrMarket, SimpleField,
    FinancialProperty, Term, RET_OK, SimpleProperty,
    BasicProperty
)

def test_direct_futu_screen():
    print("=" * 80)
    print("🚀 开始直接测试 Futu OpenD get_stock_screen 底层接口")
    print("=" * 80)
    
    # 1. 直接连接本地或 Docker 的 OpenD 网关
    host = os.getenv("FUTU_HOST", "127.0.0.1")
    port = int(os.getenv("FUTU_PORT", 11111))
    print(f"🔌 正在连接 OpenD ({host}:{port})...")
    quote_ctx = OpenQuoteContext(host=host, port=port)
    
    try:
        # 💡 必须传 30.0，富途底层 SDK 接收百分比时会自动处理
        min_val = 0.3
        target_prop = 4110  # ROE
        
        test_cases = [
            ("HK", ScrMarket.HK, "TTM", Term.LATEST),
            ("HK", ScrMarket.HK, "ANNUAL", Term.ANNUAL),
            ("US", ScrMarket.US, "TTM", Term.LATEST),
            ("US", ScrMarket.US, "ANNUAL", Term.ANNUAL),
        ]
        
        for mkt_name, mkt_enum, term_name, term_enum in test_cases:
            print(f"\n" + "-" * 60)
            print(f"🧪 测试用例: 市场=[{mkt_name}] | 周期=[{term_name}] | ROE > {min_val}%")
            print("-" * 60)
            
            req = StockScreenRequest()
            req.add_simple_field(SimpleField.MARKET, [mkt_enum])
            req.add_retrieve_basic(BasicProperty.CODE)
            req.add_retrieve_basic(BasicProperty.NAME)
            req.add_financial_property(target_prop, term=term_enum, lower=min_val, upper=None)
            req.add_retrieve_financial(target_prop, term=term_enum)
            req.add_retrieve_simple(SimpleProperty.MARKET_CAP)
            
            ret, data = quote_ctx.get_stock_screen(req)
            
            if ret == RET_OK:
                is_last_page, all_count, items = data[0], data[1], data[2]  # type: ignore
                if int(all_count) > 3000:
                    print(f"❌ 被静默丢弃 (Silent Drop)! 返回了 {all_count} 只股票，说明 {mkt_name} 市场不支持 {term_name} 周期的 ROE 过滤。")
                elif all_count == 0:
                    print(f"⚠️ 过滤生效，但返回 0 只！说明富途可能有该字段，但暂无符合条件数据。")
                else:
                    print(f"✅ 过滤完美生效！匹配到 {all_count} 只标的。")
                    if items:
                        print(f"\n   📄 数据逐行解析打印 (前 3 条):")
                        for idx, item in enumerate(items[:3]):
                            # 💡 增加类型守卫：向 Pylance 证明这是一个字典，消除 "str 没有 get 属性" 的警告
                            if not isinstance(item, dict): continue
                            stock_id = item.get('stock_id', 'N/A')
                            code = item.get('code', 'N/A')
                            name = item.get('name', 'N/A')
                            print(f"   [{idx+1}] 股票 ID: {stock_id} | 代码: {code} | 名称: {name}")
                            for res in item.get('results', []):
                                # 💡 同理，确保内层的结果也是字典类型
                                if not isinstance(res, dict): continue
                                r_type = res.get('type')
                                prop = res.get('property', {})
                                prop_name = prop.get('name')
                                term = prop.get('term', 'N/A')
                                
                                v_type = res.get('value_type')
                                val = None
                                if v_type == 1: val = res.get('sval')
                                elif v_type == 2: val = res.get('ival')
                                elif v_type == 3: val = res.get('aval')
                                elif v_type == 4: val = res.get('dval')
                                else: val = res.get('dval') or res.get('ival') or res.get('sval')
                                
                                prop_label = f"ROE({prop_name})" if prop_name == 4110 else f"市值({prop_name})" if prop_name == 2301 else prop_name
                                print(f"       -> [指标] 类型: {r_type:<10} | 属性: {prop_label:<12} | 周期: {term:<4} | 值: {val}")
            else:
                print(f"❌ 请求报错: {data}")
                
            import time
            time.sleep(1) # 略微休眠防限流
            
    finally:
        quote_ctx.close()
        print("\n🛑 OpenD 连接已安全关闭。")

if __name__ == "__main__":
    test_direct_futu_screen()