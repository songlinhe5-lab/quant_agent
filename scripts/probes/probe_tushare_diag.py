"""
Tushare 诊断脚本（手动运行，环境会跳过含网络的执行）

用法（清掉本机失效代理后再跑，避免被 127.0.0.1:10808 卡死）：
  env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    TUSHARE_TOKEN=你的token python3 scripts/probe_tushare_diag.py
"""

import os
import sys
import traceback

# 强制清代理（双保险，service 内部也会清一次）
for k in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(k, None)
os.environ["NO_PROXY"] = "*"

if not os.environ.get("TUSHARE_TOKEN"):
    print("✗ 请通过环境变量传入 TUSHARE_TOKEN")
    sys.exit(1)

# 1) 裸调 tushare，拿到最原始异常
print("=== 1. 裸调 tushare.pro_api ===")
try:
    import tushare as ts

    ts.set_token(os.environ["TUSHARE_TOKEN"])
    pro = ts.pro_api()
    df = pro.stock_basic(fields="ts_code,name")
    print("OK stock_basic rows =", len(df))
    print(df.head(2).to_dict(orient="records"))
except Exception:
    traceback.print_exc()
    print("\n裸调失败，停止。上面是真实根因（代理/网络/token/积分）。")
    sys.exit(2)

# 2) 走 service 封装层，确认 message/category 透传正确
print("\n=== 2. service 封装层 ===")
from backend.services.tushare.service import tushare_service as t  # noqa: E402

for name, fn in [
    ("list", lambda: t.get_stock_basic(fields="ts_code,name")),
    ("weekly", lambda: t.get_lowfreq_history("SH.600519", freq="weekly", num=3)),
    ("balance", lambda: t.get_balancesheet("SH.600519", period="20231231")),
    ("macro", lambda: t.get_macro("cn_cpi")),
    ("health", lambda: t.get_health_status()),
]:
    try:
        r = fn()
        print(f"{name:8s} -> success={r.get('success')} | category={r.get('category')} | {r.get('message')}")
    except Exception:
        traceback.print_exc()
