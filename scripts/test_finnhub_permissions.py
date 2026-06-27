import os
import requests

def verify_finnhub_endpoints(api_key: str):
    """
    验证 Finnhub API Key 对各类基础与高级接口的访问权限
    """
    if not api_key or api_key == "在此处填入你的_API_KEY":
        print("❌ 错误: 未提供有效的 FINNHUB_API_KEY。")
        print("👉 请在项目根目录的 .env 文件中配置 FINNHUB_API_KEY，或直接修改脚本底部的 API_KEY 变量。")
        return
        
    if not api_key.isascii():
        print("❌ 错误: API Key 包含非 ASCII 字符 (如中文)。请检查是否误复制了多余的字符。")
        return

    base_url = "https://finnhub.io/api/v1"
    headers = {"X-Finnhub-Token": api_key}

    # 预定义探测列表：分类 + 接口路径
    endpoints_to_test = [
        # --- 🟢 常见免费接口 (基础数据) ---
        ("实时行情 (Quote)", "/quote?symbol=AAPL"),
        ("公司画像 (Profile)", "/stock/profile2?symbol=AAPL"),
        ("市场新闻 (Market News)", "/news?category=general"),
        ("基本面指标 (Basic Financials)", "/stock/metric?symbol=AAPL&metric=all"),
        ("美股标的列表 (Symbol List)", "/stock/symbol?exchange=US"),

        # --- 🌐 宏观经济数据 (Economic Data) ---
        ("国家/地区列表 (Country List)", "/country"),
        ("经济指标代码 (Economic Code)", "/economic/code"),
        ("宏观经济数据 (Economic Data)", "/economic?code=MA-USA-656880"),
        ("宏观经济日历 (Economic Calendar)", "/calendar/economic"),

        # --- 🔴 常见高级接口 (Premium / All-in-One 专属) ---
        ("高频逐笔数据 (Tick Data)", "/stock/tick?symbol=AAPL&date=2023-10-02"),
        ("期权链 (Option Chain)", "/option/chain?symbol=AAPL"),
        ("分析师盈利预测 (Estimates)", "/stock/eps-estimate?symbol=AAPL"),
        ("财报日历 (Earnings Calendar)", "/calendar/earnings?from=2023-10-01&to=2023-10-15"),
        ("机构持仓 (Fund Ownership)", "/stock/fund-ownership?symbol=AAPL"),
        ("ESG 评分 (ESG Scores)", "/stock/esg?symbol=AAPL"),
        ("内幕交易 (Insider Transactions)", "/stock/insider-transactions?symbol=AAPL"),
    ]

    print(f"🔍 开始使用 API Key (尾号 ***{api_key[-4:]}) 测试 Finnhub 接口权限...\n")
    print("-" * 75)
    print(f"{'接口类别':<30} | {'测试结果':<15} | {'返回信息/状态码'}")
    print("-" * 75)

    for name, path in endpoints_to_test:
        url = f"{base_url}{path}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            status = resp.status_code
            
            if status == 200:
                result = "✅ 允许访问"
                try:
                    # 简单预览一下返回格式
                    data = resp.json()
                    preview = str(data)[:60] + "..." if data else "空数据"
                except Exception:
                    raw_text = resp.text.strip().replace('\n', ' ')
                    preview = f"⚠️ 非 JSON: {raw_text[:60]}..."
            elif status == 403:
                result = "🚫 拒绝访问"
                preview = "403 Forbidden (需升级高级版)"
            elif status == 429:
                result = "⚠️ 频次限流"
                preview = "429 Too Many Requests"
            elif status == 401:
                result = "❌ 密钥无效"
                preview = "401 Unauthorized"
            else:
                result = f"❓ 未知状态"
                preview = f"HTTP {status}"

            print(f"{name:<30} | {result:<15} | {preview}")
            
        except Exception as e:
            print(f"{name:<30} | ❌ 请求失败 | {str(e)[:30]}")

    print("-" * 75)
    print("验证完成！\n")
    print("💡 提示: ")
    print("  1. 如果显示 '✅ 允许访问' 但数据为空，说明接口可用但当前参数无数据。")
    print("  2. 如果大量基础接口报 429，说明并发过高，请稍后重试。")

if __name__ == "__main__":
    # 请替换为你真实的 API Key，或确保环境变量中已配置 FINNHUB_API_KEY
    API_KEY = os.getenv("FINNHUB_API_KEY", "d2coo7pr01qihtcsq7n0d2coo7pr01qihtcsq7ng")
    verify_finnhub_endpoints(API_KEY)
