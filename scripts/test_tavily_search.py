import os
import sys
import requests
import json

def test_tavily_search():
    # 1. 配置 API Key (优先从环境变量读取，否则可直接替换下方预设值)
    API_KEY = os.getenv("TAVILY_API_KEY", "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")
    URL = "https://api.tavily.com/search"

    if API_KEY == "tvly-your_key_here" or not API_KEY:
        print("⚠️ 提示: 你当前使用的似乎是默认的占位符 Key。")
        print("请将代码中的 'tvly-your_key_here' 替换为你真实的 Tavily API Key，或在 .env 文件中配置 TAVILY_API_KEY。")

    # 2. 构建请求参数
    payload = {
        "api_key": API_KEY,
        "query": "Nvidia latest earnings report 2026", # 搜索测试词
        "search_depth": "basic",                      # 'basic' 速度快；'advanced' 搜索更深但耗时更长，且消耗 2 个额度
        "max_results": 3,                             # 限制返回的结果数量
        "include_answer": False                       # 是否让 Tavily 内部大模型生成一段总结性的回答
    }

    print(f"🔍 正在测试 Tavily Search API...\n关键词: {payload['query']}\n")

    # 3. 发送请求并解析
    try:
        response = requests.post(URL, json=payload, timeout=15)

        if response.status_code != 200:
            print(f"❌ 测试失败: HTTP {response.status_code}")
            try:
                error_data = response.json()
                print(f"👉 报错信息: {json.dumps(error_data, indent=2, ensure_ascii=False)}")
            except:
                print(f"👉 原始响应内容: {response.text}")
            
            if response.status_code in (401, 403):
                print("\n💡 原因排查: 401/403 错误通常意味着你的 API Key 不正确或无效。请检查是否有多余的空格。")
            sys.exit(1)

        # 4. 提取并打印核心数据
        results = response.json().get("results", [])
        print("✅ 测试成功！Tavily 返回的数据（已自动提取纯文本正文）如下：\n")
        for idx, item in enumerate(results, 1):
            print(f"[{idx}] {item.get('title')}")
            print(f"    链接: {item.get('url')}")
            print(f"    内容截取: {item.get('content')[:150]}...\n") # 网页正文通常很长，这里只截取前 150 字符演示

    except requests.exceptions.RequestException as e:
        print(f"🚨 网络请求超时或失败: {e}")

if __name__ == "__main__":
    test_tavily_search()
