import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

def test_dashboard_widgets():
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        print("❌ 请在 .env 中配置 FINNHUB_API_KEY")
        return

    base_url = "https://finnhub.io/api/v1"
    headers = {"X-Finnhub-Token": api_key}

    print("=" * 60)
    print("📊 大盘看板组件数据测试 (Finnhub)")
    print("=" * 60)

    # --- 1. 测试财报日历 ---
    today = datetime.now()
    next_week = today + timedelta(days=7)
    print(f"\n📅 1. 获取近期财报日历 ({today.strftime('%Y-%m-%d')} 至 {next_week.strftime('%Y-%m-%d')}):")
    
    earnings_url = f"{base_url}/calendar/earnings"
    params_earnings = {
        "from": today.strftime("%Y-%m-%d"),
        "to": next_week.strftime("%Y-%m-%d")
    }
    try:
        resp = requests.get(earnings_url, params=params_earnings, headers=headers)
        if resp.status_code == 200:
            calendar = resp.json().get("earningsCalendar", [])
            print(f"✅ 成功获取到 {len(calendar)} 条即将发布的财报信息。")
            # 过滤打印几个大家熟悉的头部公司，或者打印前 3 个
            for item in calendar[:3]:
                print(f"  - 股票: {item.get('symbol'):<6} | 日期: {item.get('date')} | 季度: Q{item.get('quarter')} | 预期 EPS: {item.get('epsEstimate', 'N/A')}")
        else:
            print(f"❌ 获取失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 发生异常: {e}")

    # --- 2. 测试内幕交易 ---
    test_symbol = "AAPL"
    print(f"\n🕵️‍♂️ 2. 获取高管内幕交易记录 (以 {test_symbol} 为例):")
    insider_url = f"{base_url}/stock/insider-transactions"
    try:
        resp = requests.get(insider_url, params={"symbol": test_symbol}, headers=headers)
        if resp.status_code == 200:
            transactions = resp.json().get("data", [])
            print(f"✅ 成功获取到 {len(transactions)} 条高管交易记录。")
            for item in transactions[:3]:
                trade_date = item.get('transactionDate')
                name = item.get('name', 'N/A')[:15]
                shares = item.get('transactionPrice', 0)
                change = item.get('change', 0)
                action = "🟢 买入" if change > 0 else "🔴 卖出"
                print(f"  - {trade_date} | {name:<15} | 动作: {action} | 变动股数: {change:+,} | 交易价: ${shares}")
        else:
            print(f"❌ 获取失败: HTTP {resp.status_code}")
    except Exception as e:
        print(f"❌ 发生异常: {e}")

if __name__ == "__main__":
    test_dashboard_widgets()