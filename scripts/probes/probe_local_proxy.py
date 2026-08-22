"""探查本机 requests 实际捡到的代理来源 + 清掉全部可能变量后东财是否直连。运行: bash -c 'unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy; uv run python scripts/probe_local_proxy.py'"""

import os

import akshare as ak
import requests

print("=== 当前环境代理变量 ===")
for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy"]:
    v = os.environ.get(k)
    print(f"  {k} = {v if v else '(unset)'}")

print("=== requests 解析到的代理 ===")
proxies = requests.utils.get_environ_proxies("https://push2his.eastmoney.com")
print("  requests proxies for eastmoney:", proxies)

print("=== 尝试 akshare 强制清代理后直连 ===")
try:
    ak.set_proxy(None)
    print("  ak.set_proxy(None) done")
except Exception as e:
    print("  ak.set_proxy failed:", e)

import asyncio  # noqa: E402
import time  # noqa: E402


async def main():
    t = time.perf_counter()
    try:
        df = await asyncio.to_thread(ak.stock_zh_a_hist, symbol="600519", period="daily", adjust="qfq")
        print("LOCAL(direct) stock_zh_a_hist OK %.0fms rows=%d" % ((time.perf_counter() - t) * 1000, len(df)))
    except Exception as e:
        print(
            "LOCAL(direct) stock_zh_a_hist FAIL %.0fms %s: %s"
            % ((time.perf_counter() - t) * 1000, type(e).__name__, str(e)[:160])
        )


asyncio.run(main())
