import asyncio
import httpx
import json
import os
import sys

# 设置控制台颜色
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

endpoints = [
    {
        "category": "1. 系统核心与网关基建接口",
        "tests": [
            {"method": "GET", "path": "/health", "params": {}, "desc": "系统健康检查 (验证 Redis 连通性与 Futu 网关存活状态)"},
            {"method": "GET", "path": "/settings/preferences", "params": {}, "desc": "用户偏好配置 (查询 Redis 中的降级开关与系统设置)"},
            {"method": "GET", "path": "/trade/account", "params": {"market": "HK"}, "desc": "交易账户资产数据 (直连 Futu 获取真实/模拟盘资金与实时持仓明细)"},
            {"method": "GET", "path": "/trade/portfolio", "params": {}, "desc": "内部风控核算 (查询账户全局资产、夏普比率与风险敞口)"},
            {"method": "GET", "path": "/trade/trades", "params": {}, "desc": "本地交易流水 (查询本地 SQLite 中的历史订单记录)"},
        ]
    },
    {
        "category": "2. 第三方数据接口 (通过 Backend 网关代理路由)",
        "tests": [
            {"method": "GET", "path": "/market/quote", "params": {"ticker": "HK.00700"}, "desc": "实时行情快照 (直连 Futu L2 盘口，若断网则降级 Yahoo)"},
            {"method": "GET", "path": "/market/history", "params": {"ticker": "HK.00700", "num": 5}, "desc": "历史K线趋势 (直连 Futu 历史 K 线额度，支持多周期)"},
            {"method": "GET", "path": "/market/tech-indicators", "params": {"ticker": "US.AAPL", "lookback_days": 1}, "desc": "技术指标矩阵 (请求 Yahoo/Futu K 线并聚合计算 MA/MACD/RSI/布林带)"},
            {"method": "GET", "path": "/market/fundamental/HK.00700", "params": {}, "desc": "公司基本面与估值 (获取 Futu 深度 PE/PB/市值 数据，断连走 Yahoo 备用)"},
            {"method": "GET", "path": "/market/fund-flow", "params": {"ticker": "HK.00700"}, "desc": "资金流向与席位 (Futu 独家主力资金追踪与经纪商排队追踪)"},
            {"method": "GET", "path": "/market/option-chain", "params": {"ticker": "US.AAPL"}, "desc": "股票期权链 (获取 Futu OCC 标准格式的衍生品合约列表)"},
            {"method": "GET", "path": "/macro/calendar", "params": {"days_ahead": 7}, "desc": "宏观经济日历 (调用 Finnhub API 获取高影响经济事件)"},
            {"method": "GET", "path": "/market/search", "params": {"q": "AAPL"}, "desc": "股票代码智能补全 (调用 Yahoo 搜索引擎代理并过滤非股票资产)"},
        ]
    },
    {
        "category": "3. 智能量化选股 (Screener) 接口",
        "tests": [
            {"method": "GET", "path": "/screener/suggestions", "params": {"limit": 3}, "desc": "获取选股灵感 (从后端拉取随机的 NLP 提示词)"},
            {"method": "POST", "path": "/screener/translate", "params": {"query": "港股，市值大于100亿，且出现MACD金叉"}, "desc": "NLP 转 DSL (调用大模型与 RAG 知识库解析意图)"},
            {"method": "POST", "path": "/screener/run", "params": {"dsl": '{"dsl_display":"market:hk div_yield:>5 pe:<15 roe:>20","markets":["HK"],"filters":[{"field":"DIVIDEND_YIELD","type":"featured","min_value":5},{"field":"PE","type":"financial","max_value":15},{"field":"ROE","type":"financial","min_value":20}]}', "page": 1, "page_size": 3}, "desc": "在线条件选股 (调用 Futu OpenD 发起多市场扫盘，带服务端分页)"},
        ]
    }
]

async def verify_all_endpoints():
    base_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api").rstrip('/')
    print(f"\n{Colors.BOLD}{Colors.HEADER}🚀 开始全面验证后端接口与第三方数据源 (Target: {base_url}){Colors.ENDC}\n")

    async with httpx.AsyncClient(timeout=15.0) as client:
        for group in endpoints:
            print(f"{Colors.OKBLUE}=================================================={Colors.ENDC}")
            print(f"{Colors.BOLD}{Colors.OKCYAN}📁 {group['category']}{Colors.ENDC}")
            print(f"{Colors.OKBLUE}=================================================={Colors.ENDC}")
            
            for test in group['tests']:
                desc = test['desc']
                method = test['method']
                path = test['path']
                params = test.get('params', {})
                
                print(f"\n{Colors.BOLD}🧪 接口: {path}{Colors.ENDC}")
                print(f"📝 作用: {desc}")
                
                try:
                    # 发起 HTTP 请求
                    if method == "GET":
                        resp = await client.get(f"{base_url}{path}", params=params)
                    else:
                        resp = await client.post(f"{base_url}{path}", json=params)
                        
                    status = resp.status_code
                    if status == 200:
                        data = resp.json()
                        # 针对不同接口返回的数据结构，兼容解析状态
                        status_val = data.get("status", "unknown") if isinstance(data, dict) else "ok"
                        
                        if status_val in ["success", "ok", "healthy", "degraded"]:
                            print(f"  {Colors.OKGREEN}✅ [HTTP 200] 测试通过{Colors.ENDC}")
                            # 截断超长 JSON，保持日志整洁
                            res_str = json.dumps(data, ensure_ascii=False)
                            if len(res_str) > 150:
                                print(f"  📄 返回摘要: {res_str[:150]} ...")
                            else:
                                print(f"  📄 返回数据: {res_str}")
                                
                        elif status_val == "warning":
                            print(f"  {Colors.WARNING}⚠️ [HTTP 200] 业务警告: {data.get('message')}{Colors.ENDC}")
                            
                        else:
                            print(f"  {Colors.FAIL}❌ [HTTP 200] 业务报错: {data.get('message', data)}{Colors.ENDC}")
                            
                    elif status in [400, 401, 403, 404, 422]:
                        # 获取详细的 FastAPI 抛出的 Error Detail
                        err_detail = resp.text
                        try:
                            err_detail = resp.json().get("detail", resp.text)
                        except:
                            pass
                        print(f"  {Colors.WARNING}⚠️ [HTTP {status}] 请求拦截或客户端错误: {err_detail}{Colors.ENDC}")
                    else:
                        print(f"  {Colors.FAIL}❌ [HTTP {status}] 服务器内部崩溃: {resp.text}{Colors.ENDC}")
                        
                except httpx.TimeoutException:
                    print(f"  {Colors.FAIL}💥 [请求超时] 第三方接口响应过慢或服务挂起 (Timeout > 15s){Colors.ENDC}")
                except Exception as e:
                    print(f"  {Colors.FAIL}💥 [网络异常] 无法连接到后端，请确认网关已启动: {e}{Colors.ENDC}")
                    
    print(f"\n{Colors.BOLD}{Colors.HEADER}🎉 接口全面验证测试执行完毕！{Colors.ENDC}\n")

if __name__ == "__main__":
    try:
        asyncio.run(verify_all_endpoints())
    except KeyboardInterrupt:
        print("\n[System] 已手动中断测试。")