import asyncio
import httpx
import json
import os
import sys
from dotenv import load_dotenv

# 确保可以正确导入 backend 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

async def get_auth_token(client, base_url):
    """尝试使用默认 admin 账号获取 token，以便测试需要鉴权的接口"""
    try:
        resp = await client.post(f"{base_url}/auth/login", data={"username": "admin", "password": "admin"})
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None

async def test_run_screener():
    # 自动适配您的后端 API 网关地址
    base_url = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8000/api").rstrip('/')
    
    print(f"🚀 开始全面测试智能选股器 (Screener) API: {base_url}/screener\n")
    
    try:
        async with httpx.AsyncClient() as client:
            # 0. 获取鉴权 Token
            token = await get_auth_token(client, base_url)
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            if not token:
                print("⚠️ 未能获取 admin Token，部分需要鉴权的接口（如词库、订阅）可能会返回 401 Unauthorized。\n")

            # ==========================================
            # 1. 测试获取选股灵感 (/screener/suggestions)
            # ==========================================
            url_suggestions = f"{base_url}/screener/suggestions"
            print(f"📡 [1] GET {url_suggestions}")
            resp = await client.get(url_suggestions, params={"limit": 3})
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200:
                print(f"   ✅ 返回灵感: {json.dumps(resp.json().get('data', []), ensure_ascii=False)}")

            # ==========================================
            # 2. 测试 NLP 转 DSL (/screener/translate)
            # ==========================================
            url_translate = f"{base_url}/screener/translate"
            print(f"\n📡 [2] POST {url_translate}")
            payload_translate = {"query": "港股，市值大于100亿的科技股"}
            resp = await client.post(url_translate, json=payload_translate, timeout=15.0)
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200:
                print(f"   ✅ 转译结果: {resp.json().get('data')}")

            # ==========================================
            # 3. 测试在线条件选股 (/screener/run)
            # ==========================================
            url_run = f"{base_url}/screener/run"
            print(f"\n📡 [3] POST {url_run}")
            payload_run = {
                "dsl": '{"dsl_display":"market:hk div_yield:>5 pe:<15 roe:>20","markets":["HK"],"filters":[{"field":"DIVIDEND_YIELD","type":"featured","min_value":5},{"field":"PE","type":"financial","max_value":15},{"field":"ROE","type":"financial","min_value":20}]}',
                "page": 1,
                "page_size": 3
            }
            resp = await client.post(url_run, json=payload_run, timeout=45.0)
            print(f"   Status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"   ✅ 筛选成功！总计匹配: {data.get('total', 0)} 只")
                if data.get("data"):
                    print(f"   📄 截取首条数据: {json.dumps(data['data'][0], ensure_ascii=False)}")
            else:
                print(f"   ❌ 筛选失败: {resp.text}")

            # ==========================================
            # 4. 测试自定义词库管理 (/screener/dictionary)
            # ==========================================
            url_dict = f"{base_url}/screener/dictionary"
            print(f"\n📡 [4] RAG 词库管理测试")
            if token:
                print(f"   -> POST {url_dict}")
                dict_payload = {"desc": "测试专用高股息", "rule": "- 测试专用高股息 -> DIVIDEND_RATIO (simple) min_value: 0.08"}
                resp = await client.post(url_dict, json=dict_payload, headers=headers)
                print(f"      Status: {resp.status_code}")
                
                print(f"   -> GET {url_dict}")
                resp = await client.get(url_dict, headers=headers)
                print(f"      Status: {resp.status_code}")
                if resp.status_code == 200:
                    items = resp.json().get('data', [])
                    print(f"      ✅ 当前词库共 {len(items)} 条规则")

                url_dict_batch = f"{base_url}/screener/dictionary/batch"
                print(f"   -> POST {url_dict_batch}")
                batch_payload = {"items": [
                    {"desc": "测试批量因子A", "rule": "A -> A"},
                    {"desc": "测试批量因子B", "rule": "B -> B"}
                ]}
                resp = await client.post(url_dict_batch, json=batch_payload, headers=headers)
                print(f"      Status: {resp.status_code}")

                print(f"   -> DELETE {url_dict}")
                for d in [dict_payload, {"desc": "测试批量因子A", "rule": "A -> A"}, {"desc": "测试批量因子B", "rule": "B -> B"}]:
                    await client.request("DELETE", url_dict, json=d, headers=headers)
                print(f"      ✅ 测试词条已清理")
            else:
                print("   ⚠️ 缺少 Token，跳过需鉴权的词库测试")

            # ==========================================
            # 5. 测试订阅任务管理 (/screener/subscribe)
            # ==========================================
            print(f"\n📡 [5] 定时订阅任务管理测试")
            if token:
                url_sub = f"{base_url}/screener/subscribe"
                print(f"   -> POST {url_sub}")
                sub_payload = {"name": "API自动化测试策略", "dsl": '{"dsl_display":"market:us mktcap:>100B","markets":["US"],"filters":[{"field":"MARKET_CAP","type":"simple","min_value":100000000000}]}', "trigger_time": "15:30"}
                resp = await client.post(url_sub, json=sub_payload, headers=headers)
                print(f"      Status: {resp.status_code}")
                
                url_subs = f"{base_url}/screener/subscriptions"
                print(f"   -> GET {url_subs}")
                resp = await client.get(url_subs, headers=headers)
                print(f"      Status: {resp.status_code}")
                
                sub_id = None
                if resp.status_code == 200:
                    subs = resp.json().get("data", [])
                    print(f"      ✅ 当前共有 {len(subs)} 个订阅任务")
                    for s in subs:
                        if s["name"] == "API自动化测试策略":
                            sub_id = s["id"]
                            break
                
                if sub_id:
                    url_time = f"{base_url}/screener/subscriptions/{sub_id}/time"
                    print(f"   -> PUT {url_time}")
                    resp = await client.put(url_time, json={"trigger_time": "10:00"}, headers=headers)
                    print(f"      Status: {resp.status_code}")

                    url_toggle = f"{base_url}/screener/subscriptions/{sub_id}/toggle"
                    print(f"   -> PUT {url_toggle}")
                    resp = await client.put(url_toggle, headers=headers)
                    print(f"      Status: {resp.status_code} (Is Active: {resp.json().get('is_active') if resp.status_code == 200 else 'N/A'})")

                    url_del = f"{base_url}/screener/subscriptions/{sub_id}"
                    print(f"   -> DELETE {url_del}")
                    resp = await client.delete(url_del, headers=headers)
                    print(f"      Status: {resp.status_code}")
            else:
                print("   ⚠️ 缺少 Token，跳过需鉴权的订阅测试")

        print("\n🎉 Screener API 全面测试执行完毕！")
            
    except httpx.ConnectError:
        print(f"💥 连接后端网关 ({base_url}) 失败！\n💡 提示：请确保您已经打开了另一个终端窗口，并运行了 `python start_all.py` 或 `uvicorn backend.main:app` 启动后端服务。")
    except Exception as e:
        print(f"💥 请求发生异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_run_screener())