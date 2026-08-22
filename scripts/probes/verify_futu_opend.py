#!/usr/bin/env python3
"""容器内 Futu OpenD 等价验证探针（F0-4）

背景：
  本机 `_test_futu_local.py` 证明"本机 OpenD 接口可用"；但 F0-4 红线是
  "本机通过 ≠ 容器通过"——data_subservice 运行在 S1 容器，经
  `docker-gw-forward@.service`(socat) 把宿主 127.0.0.1:11111 转发到
  docker0 网关，容器内用 `host.docker.internal:11111` 访问宿主 OpenD。

  本脚本在容器内裸连 OpenD（复用 `_test_futu_local.py` 风格），对**已接入
  action 对应的核心接口**做字段级断言，验证容器→OpenD 链路 + 接口结构。

用法（容器内）：
  python3 /opt/quant-agent/scripts/verify_futu_opend.py
  或经 deploy_verify.sh：ssh S1 'docker exec quant_app python3 .../verify_futu_opend.py'

前置：
  1. S1 容器 `docker-gw-forward@11111` 已 enable（systemd）
  2. 容器已 `pip install futu-api>=10.10.0`
  3. 容器能解析 `host.docker.internal`（= docker0 网关）
"""

import traceback
from datetime import datetime

from futu import (
    RET_OK,
    KLType,
    Market,
    OpenQuoteContext,
    SubType,
)

# ============ 配置 ============
# 容器内经 socat 转发访问宿主 OpenD（docker0 网关）
HOST = "host.docker.internal"
PORT = 11111
IS_ENCRYPT = False

HK = "HK.00700"  # 腾讯（港股，覆盖最多权限）
US = "US.AAPL"  # 苹果（美股对照）
TEST_SYMBOLS = [HK, US]


def section(title: str):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def run(label: str, fn, expect=None):
    """统一执行 + 异常隔离 + 可选字段级断言，返回 (ok, summary)。"""
    try:
        ok, msg = fn()
        if expect is not None:
            eok, emsg = expect(ok, msg)
            if not eok:
                print(f"  ❌ {label}: {msg} | 断言: {emsg}")
                return False, f"{msg} | 断言: {emsg}"
            print(f"  ✅ {label}: {msg} | 断言: {emsg}")
            return True, f"{msg} | 断言: {emsg}"
        print(f"  {'✅' if ok else '⚠️'} {label}: {msg}")
        return ok, msg
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ {label}: EXCEPTION {e!r}")
        traceback.print_exc()
        return False, f"EXCEPTION {e!r}"


def _row_count_expect(label, df_or_len, required_cols=None):
    """字段级断言：行数>0 + 关键列存在。"""
    required_cols = required_cols or []
    try:
        n = len(df_or_len) if hasattr(df_or_len, "__len__") else df_or_len
        if n == 0:
            return False, "返回 0 行（结构未验/无数据）"
        if required_cols and hasattr(df_or_len, "columns"):
            missing = [c for c in required_cols if c not in df_or_len.columns]
            if missing:
                return False, f"缺失关键列: {missing}"
        return True, f"{n} 行, 关键列齐({required_cols or 'n/a'})"
    except Exception as e:  # noqa: BLE001
        return False, f"断言异常: {e!r}"


def main():
    print(f"🚀 容器内 Futu OpenD 等价验证  | {datetime.now()}")
    print(f"   连接: {HOST}:{PORT}  encrypt={IS_ENCRYPT}  (F0-4: 容器→宿主 OpenD 经 socat 转发)")

    results = {}

    # ---- 基础连通（宿主 OpenD 可达性，F0-4 核心）----
    section("〇、容器→OpenD 连通")
    try:
        quote_ctx = OpenQuoteContext(host=HOST, port=PORT, is_encrypt=IS_ENCRYPT)
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ 连接失败: {e!r}")
        print("  → 请检查 S1: systemctl status docker-gw-forward@11111")
        return 1

    def _conn():
        ret, data = quote_ctx.get_global_state()
        if ret != RET_OK:
            return False, f"get_global_state 失败: {data}"
        return True, f"global_state OK, 市场状态={data.get('market_sz') if isinstance(data, dict) else data}"

    results["CONNECT"] = run("CONNECT/容器→OpenD", _conn)

    # ---- 已接入核心接口（字段级断言，对应 futu_worker action）----
    section("一、行情（QUOTE/HISTORY）")
    try:
        quote_ctx.subscribe(TEST_SYMBOLS, [SubType.QUOTE], is_first_push=False)
    except Exception:  # noqa: BLE001
        pass

    def _quote():
        ret, data = quote_ctx.get_stock_quote(TEST_SYMBOLS)
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("QUOTE", data, required_cols=["code", "last_price"])
        return ok, f"QUOTE {len(data)} 行 | {d}"

    results["QUOTE"] = run("QUOTE (get_stock_quote)", _quote)

    def _history():
        res = quote_ctx.request_history_kline(HK, ktype=KLType.K_DAY, max_count=10)
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("HISTORY", data, required_cols=["code", "close"])
        return ok, f"HISTORY {len(data)} 根K | {d}"

    results["HISTORY"] = run("HISTORY (request_history_kline)", _history)

    section("二、数据正确性基座（G8：REHAB/TRADING_DAYS/MARKET_STATE）")

    def _rehab():
        ret, data = quote_ctx.get_rehab(HK)
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("REHAB", data, required_cols=["ex_div_date"])
        return ok, f"REHAB {len(data)} 行 | {d}"

    results["REHAB"] = run("REHAB (get_rehab)", _rehab)

    def _trading_days():
        res = quote_ctx.request_trading_days(Market.HK, "2026-01-01", "2026-01-31")
        ret, data = res[0], res[1]
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("TRADING_DAYS", data, required_cols=["time"])
        return ok, f"TRADING_DAYS {len(data)} 天 | {d}"

    results["TRADING_DAYS"] = run("TRADING_DAYS (request_trading_days)", _trading_days)

    def _market_state():
        ret, data = quote_ctx.get_market_state([HK, US])
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("MARKET_STATE", data, required_cols=["code", "market_state"])
        return ok, f"MARKET_STATE {len(data)} 行 | {d}"

    results["MARKET_STATE"] = run("MARKET_STATE (get_market_state)", _market_state)

    section("三、板块（G6：OWNER_PLATE + 热力图）")

    def _owner_plate():
        ret, data = quote_ctx.get_owner_plate(HK)
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("OWNER_PLATE", data, required_cols=["plate_code", "plate_name"])
        return ok, f"OWNER_PLATE {len(data)} 板块 | {d}"

    results["OWNER_PLATE"] = run("OWNER_PLATE (get_owner_plate)", _owner_plate)

    section("四、基本面（G1：FINANCIALS）")

    def _financials():
        from futu import FinancialType

        ret, data = quote_ctx.get_financials_statements(
            code=HK, financial_type=FinancialType.ANNUAL, start="2023-01-01", end="2025-12-31"
        )
        if ret != RET_OK:
            return False, data
        ok, d = _row_count_expect("FINANCIALS", data, required_cols=["time"])
        return ok, f"FINANCIALS {len(data)} 期 | {d}"

    results["FINANCIALS"] = run("FINANCIALS (get_financials_statements)", _financials)

    # ---- 汇总 ----
    section("📊 汇总")
    passed = sum(1 for v in results.values() if v[0] is True)
    failed = sum(1 for v in results.values() if v[0] is not True)
    print(f"  ✅ 通过: {passed}  |  ❌ 失败/未验: {failed}  |  总计: {len(results)}")
    if failed:
        print("  ⚠️ 存在失败项，容器内 OpenD 等价验证未全通")
        return 1
    print("  🎉 容器内 OpenD 等价验证全部通过（F0-4）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
