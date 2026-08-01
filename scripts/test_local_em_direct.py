"""本机清代理后实测东财直连是否可用。运行: HTTP_PROXY= HTTPS_PROXY= uv run python scripts/test_local_em_direct.py"""

import asyncio
import time

import akshare as ak


async def main():
    t = time.perf_counter()
    try:
        df = await asyncio.to_thread(ak.stock_zh_a_hist, symbol="600519", period="daily", adjust="qfq")
        print("LOCAL(no-proxy) stock_zh_a_hist OK %.0fms rows=%d" % ((time.perf_counter() - t) * 1000, len(df)))
    except Exception as e:
        print(
            "LOCAL(no-proxy) stock_zh_a_hist FAIL %.0fms %s: %s"
            % ((time.perf_counter() - t) * 1000, type(e).__name__, str(e)[:160])
        )


asyncio.run(main())
