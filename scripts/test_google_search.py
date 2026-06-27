import requests
import sys
import os
import json

def test_google_search():
    # 1. 核心配置凭证 (优先从环境变量 .env 读取，若无则使用下方兜底值)
    API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY", "AIzaSyAWkdAuzHCN63J-8sA8HWrTkmCZz5ZfD0A")
    CX_ID = os.getenv("GOOGLE_SEARCH_CX", "b55cf8e8acc394949")
    URL = "https://customsearch.googleapis.com/customsearch/v1"

    if not API_KEY or not CX_ID:
        print("❌ 错误: 未找到 GOOGLE_SEARCH_API_KEY 或 GOOGLE_SEARCH_CX。")
        print("请在项目根目录的 .env 文件中配置，或直接在脚本中修改。")
        sys.exit(1)

    # 2. 构建请求参数 (参考官方文档: https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list)
    params = {
        "q": "Alphabet ROE 2026",  # 搜索关键词
        "key": API_KEY,
        "cx": CX_ID,
        "num": 3,                  # 返回结果数量 (1-10)
        "hl": "zh-CN",             # 搜索结果语言: 中文简体

        # --- 更多可选高级参数 (根据需要取消注释) ---
        # "sort": "date",          # 按日期排序
        # "siteSearch": "sec.gov", # 仅在指定网站 (如美国SEC官网) 内搜索
        # "dateRestrict": "d[7]",  # 限制在过去7天内
        # "exactTerms": "财报",    # 结果必须包含的精确词汇
        # "excludeTerms": "预测",  # 结果必须排除的词汇
    }
    
    print(f"🔍 正在测试 Google Custom Search API...\n关键词: {params['q']}\n")

    # 3. 发送请求并解析
    try:
        response = requests.get(URL, params=params, timeout=10)
        
        # 💡 专门针对非 200 状态码进行拦截与详细输出
        if response.status_code != 200:
            error_details = ""
            try:
                error_data = response.json()
                error_info = error_data.get("error", {})
                code, status, message = error_info.get("code"), error_info.get("status"), error_info.get("message")
                reason = "Unknown Reason"
                if "details" in error_info and error_info["details"]:
                    reason = error_info["details"][0].get("reason", reason)
                error_details = f"Code: {code}, Status: {status}, Reason: {reason}\nMessage: {message}"
                
                print(f"❌ 测试失败: HTTP {response.status_code}")
                if response.status_code == 403:
                    print("原因排查：请检查 Google Cloud Console 中是否已为该 Key 启用了 'Custom Search API' 或检查 API Key 的应用/IP 限制。")
                print(f"👉 Google 原始报错信息:\n{error_details}")
            except json.JSONDecodeError:
                print(f"❌ 测试失败: HTTP {response.status_code}, 无法解析 JSON 响应。")
                print(f"👉 原始响应内容: {response.text}")
            sys.exit(1)
            
        # 4. 提取并打印核心数据
        results = response.json().get("items", [])
        if not results:
            print("✅ 测试成功，但未返回任何搜索结果。")
            sys.exit(0)

        print("✅ 测试成功！返回结果如下：\n")
        for idx, item in enumerate(results, 1):
            print(f"[{idx}] {item.get('title')}")
            print(f"    链接: {item.get('link')}")
            print(f"    摘要: {item.get('snippet')}\n")

    except requests.exceptions.RequestException as e:
        print(f"🚨 接口网络请求失败或凭证错误: {e}")

if __name__ == "__main__":
    test_google_search()