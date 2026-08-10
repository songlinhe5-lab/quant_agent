"""模拟 quote.py 改造后的 get_realtime_quote / get_stock_history 逻辑，验证新浪源字段映射正确。运行: python3 verify_quote_sina.py"""

import akshare as ak

ak.set_proxy(None)  # 强制直连，清失效代理


def build_sina_symbol(code: str) -> str:
    code = code.zfill(6)
    if code.startswith(("60", "68", "90", "88")):
        return f"sh{code}"
    return f"sz{code}"


for raw in ["600519", "000001", "300750"]:
    sym = build_sina_symbol(raw)
    print(f"\n===== ticker={raw} -> sina {sym} =====")
    try:
        df = ak.stock_zh_a_daily(symbol=sym, adjust="qfq")
        latest = df.iloc[-1]
        prev_close = float(df.iloc[-2]["close"])
        last = float(latest["close"])
        change = last - prev_close
        change_pct = change / prev_close * 100
        vol = float(latest["volume"])  # 股
        amp = (float(latest["high"]) - float(latest["low"])) / prev_close * 100
        print(f"  last_price={last} prev_close={prev_close:.2f} change={change:.2f} ({change_pct:.2f}%)")
        print(f"  volume={vol:.0f} (股) amount={float(latest['amount']):.0f} amplitude={amp:.2f}%")
        print(f"  volume_str={vol / 1_000_000:.2f}M" if vol > 1_000_000 else f"  volume_str={vol / 1_000:.2f}K")
        # 历史K线映射抽查
        row = df.tail(3).iloc[-1]
        print(
            f"  kline last: time={row['date']} o={row['open']} h={row['high']} l={row['low']} c={row['close']} v={row['volume']:.0f}"
        )
    except Exception as e:
        print("  FAIL:", type(e).__name__, str(e)[:160])
