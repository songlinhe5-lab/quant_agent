"""在 CN 节点探测 akshare 历史K线替代接口可用性。运行: python3 probe_akshare_alts.py"""

import asyncio
import sys
import time

print("python:", sys.executable, sys.version.split()[0])
import akshare as ak  # noqa: E402

print("akshare:", getattr(ak, "__version__", "?"))


async def main():
    probes = {
        "stock_zh_a_hist (push2his, 已知坏)": (ak.stock_zh_a_hist, dict(symbol="600519", period="daily", adjust="qfq")),
        "stock_zh_a_daily (sina)": (ak.stock_zh_a_daily, dict(symbol="sh600519", adjust="qfq")),
        "stock_zh_a_hist_tx (tencent)": (ak.stock_zh_a_hist_tx, dict(symbol="600519", period="daily", adjust="qfq")),
        "stock_zh_a_hist_min_em (东财分钟)": (
            ak.stock_zh_a_hist_min_em,
            dict(symbol="600519", period="daily", adjust="qfq"),
        ),
        "stock_zh_a_spot_em (东财实时)": (ak.stock_zh_a_spot_em, dict()),
    }
    for name, (fn, args) in probes.items():
        t = time.perf_counter()
        try:
            df = await asyncio.to_thread(fn, **args)
            print(f"[OK]   {name}: {(time.perf_counter() - t) * 1000:.0f}ms rows={len(df)}")
        except Exception as e:
            print(f"[FAIL] {name}: {(time.perf_counter() - t) * 1000:.0f}ms {type(e).__name__}: {str(e)[:140]}")


asyncio.run(main())
