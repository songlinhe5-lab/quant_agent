#!/usr/bin/env bash
# 在 CN 节点 (120.53.84.116) 上验证 akshare 各接口耗时
# 用法: bash bench_akshare_cn.sh
set -u

echo "===== 0. 环境代理 (本地 3199ms 的元凶是失效代理 127.0.0.1:10808) ====="
env | grep -iE "proxy" || echo "NO PROXY ENV (直连, 符合 CN 节点预期)"

echo
echo "===== 1. python / akshare 版本 ====="
python3 - <<'PY'
import sys, time, asyncio
print("python:", sys.version.split()[0])
try:
    import akshare as ak
    print("akshare:", getattr(ak, "__version__", "?"))
except Exception as e:
    print("akshare import FAILED:", e)
    raise SystemExit(1)

async def main():
    calls = {
        "stock_zh_a_hist": (ak.stock_zh_a_hist, dict(symbol="600519", period="daily", adjust="qfq")),
        "stock_news_em":    (ak.stock_news_em,   dict(symbol="600519")),
        "stock_hsgt_fund_flow_summary_em": (ak.stock_hsgt_fund_flow_summary_em, dict()),
    }
    for name, (fn, args) in calls.items():
        t = time.perf_counter()
        try:
            df = await asyncio.to_thread(fn, **args)
            ms = (time.perf_counter() - t) * 1000
            print(f"[OK]   {name}: {ms:.0f} ms  rows={len(df)}")
        except Exception as e:
            ms = (time.perf_counter() - t) * 1000
            print(f"[FAIL] {name}: {ms:.0f} ms -> {type(e).__name__}: {str(e)[:160]}")

asyncio.run(main())
PY

echo
echo "===== 2. 直连东方财富网络延迟 (DNS + TCP) ====="
python3 - <<'PY'
import socket, time
for host in ["push2his.eastmoney.com", "newsapi.eastmoney.com"]:
    t = time.perf_counter()
    try:
        ip = socket.gethostbyname(host)
        s = socket.create_connection((host, 443), timeout=5)
        s.close()
        print(f"{host}: dns={ip} tcp_connect={(time.perf_counter()-t)*1000:.0f} ms")
    except Exception as e:
        print(f"{host}: FAILED {(time.perf_counter()-t)*1000:.0f} ms -> {e}")
PY
