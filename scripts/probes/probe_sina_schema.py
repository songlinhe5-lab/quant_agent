"""在 CN 节点探测 stock_zh_a_daily(新浪)的真实返回结构与单位。运行: python3 probe_sina_schema.py"""

import sys

import akshare as ak

print("python:", sys.executable)
print("akshare:", getattr(ak, "__version__", "?"))

for sym in ["sh600519", "sz000001"]:
    print(f"\n===== stock_zh_a_daily(symbol={sym!r}) =====")
    try:
        df = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")
        print("columns:", list(df.columns))
        print("dtypes:\n", df.dtypes.to_string())
        last = df.iloc[-1]
        print("last row:\n", last.to_string())
        # 估算 volume 单位：A股一手=100股，若 volume 是手则数值应能被100整除且较小
        v = float(last["volume"])
        print(f"last volume raw = {v:.0f}  (若/100={v / 100:.0f})")
    except Exception as e:
        print("FAIL:", type(e).__name__, str(e)[:160])
