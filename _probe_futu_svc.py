import asyncio, sys, traceback
sys.path.insert(0, "/app")
from data_subservice.futu_src import futu_service as svc

async def main():
    tests = [
        ("QUOTE", svc.get_quote, ("HK.00700",)),
        ("HISTORY", svc.get_history, ("HK.00700", "K_DAY", 5)),
        ("FUND_FLOW", svc.get_fund_flow, ("HK.00700",)),
        ("ORDER_BOOK", svc.get_order_book, ("HK.00700",)),
        ("OPTION_CHAIN", svc.get_option_chain, ("US.AAPL", "")),
        ("FUNDAMENTAL", svc.get_fundamental, ("HK.00700",)),
        ("STOCK_BASICINFO", svc.get_stock_basicinfo, ("HK", "STOCK")),
        ("SNAPSHOT", svc.get_market_snapshots, (["HK.00700","US.AAPL"],)),
    ]
    for label, fn, args in tests:
        try:
            r = await fn(*args)
            if isinstance(r, dict):
                st = r.get("status") or r.get("code") or ("ok" if "data" in r else "?")
                has = "data" in r
                dl = len(str(r.get("data"))) if has else 0
                detail = r.get("detail") or r.get("message") or r.get("error") or r.get("msg") or ""
                print(f"[RES] {label}: status={st} data_len={dl} detail={str(detail)[:200]}")
            else:
                ln = len(r) if hasattr(r,'__len__') else '?'
                print(f"[RES] {label}: type={type(r).__name__} len={ln}")
        except Exception as e:
            print(f"[EXC] {label}: {str(e)[:150]}")

asyncio.run(main())
print("ALL DONE")
