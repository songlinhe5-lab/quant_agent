"""S1 部署后 · G3/G4/G5/G6/G7 五大聚合接口全链路冒烟脚本。

前置：
  1. S1 VPS 上 quant-agent 主服务已起（含 futu 子服务，OpenD 经 socat 已固化连通）
  2. 本脚本在能访问 S1 API 的机器上运行（同 Tailscale 或经 Cloudflare Pages/直连）
  3. pip install httpx
  4. python _smoke_g_series_s1.py --base http://100.102.223.44:8000

设计目标：
  - 不走本地 facade 单测（本地无 OpenD），而是打真实 HTTP 路由，验证端到端管道
  - 对五大聚合接口做"防御式列名解析"契约断言：
      · 返回 status 必须是 success/degraded（不准 error 假绿）
      · 派生字段（如 G4 的 break_even / G6 的 breadth_ratio / G7 的 upside_pct）
        必须真实算出（非 None），否则说明 Futu 10.10 列名与解析器预期不符 → 需要回炉校准
  - 任一契约失败 → 打印原始 data 前若干行，供人工定位 Futu 真实列名

注：本脚本只读取，不触发任何交易动作。
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any

import httpx

# ============ 配置 ============
DEFAULT_BASE = "http://100.102.223.44:8000"
# 港股/美股对照标的，覆盖 Futu 权限最广的两个市场
HK = "HK.00700"  # 腾讯
US = "US.AAPL"  # 苹果

# 各接口需要"真实算出而非 None"的关键派生字段（零幻觉红线校验）
REQUIRED_DERIVED_FIELDS = {
    # G3：主力筹码分层
    "capital-distribution": {
        "ticker": HK,
        "path": f"/api/v1/market/capital-distribution/{HK}",
        "must_have": ["main_net", "retail_net", "institution_dominance", "signals"],
        "desc": "G3 主力净额/散户净额/机构主导度/背离信号",
    },
    # G4：期权损益实验室（STRANGLE 跨式）
    "option-strategy-lab": {
        "ticker": US,
        "path": f"/api/v1/market/option-strategy-lab?ticker={US}&strategy_type=STRANGLE&spread=5",
        "must_have": ["available", "break_even", "max_profit", "max_loss", "payoff_curve"],
        "desc": "G4 损益实验室（盈亏平衡/最大盈亏/损益曲线，纯代数非 BS）",
    },
    # G5：FedWatch 面板
    "fed-watch": {
        "ticker": None,
        "path": "/api/v1/macro/fed-watch",
        "must_have": ["next_meeting_implied_rate", "policy_slope", "meetings"],
        "desc": "G5 FedWatch（下一会议隐含利率/政策斜率/会议序列）",
    },
    # G6：板块热力图
    "heat-map": {
        "ticker": None,
        "path": "/api/v1/market/heat-map/HK",
        "must_have": ["breadth_ratio", "avg_change", "top_gainers", "top_losers"],
        "desc": "G6 板块热力图（涨跌比/平均涨跌/领涨领跌）",
    },
    # G7：卖方共识 vs 实际基本面
    "analyst-vs-fundamental": {
        "ticker": US,
        "path": f"/api/v1/market-fundamental/analyst-vs-fundamental/{US}",
        "must_have": ["upside_pct", "verdict", "consensus_is_third_party_expectation"],
        "desc": "G7 卖方共识 vs 基本面（上行空间/结论/第三方观点标记）",
    },
}


def section(title: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {title}")
    print("=" * 72)


def _dig(data: Any, *keys: str) -> Any:
    """从嵌套 dict 中逐层取键，任意一层缺失即返回 None。"""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def check(name: str, spec: dict, base: str) -> tuple[bool, str]:
    """打一个接口，做 status + 派生字段契约断言，返回 (ok, detail)。"""
    url = base.rstrip("/") + spec["path"]
    try:
        with httpx.Client(timeout=30.0) as cli:
            r = cli.get(url)
    except Exception as e:  # noqa: BLE001
        return False, f"HTTP 请求失败: {type(e).__name__}: {e}"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:300]}"

    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        return False, f"响应非 JSON: {r.text[:300]}"

    # 路由外层可能是 {data: {...}} 或裸 {...}
    payload = body.get("data", body) if isinstance(body, dict) else body
    status = _dig(payload, "status") or _dig(body, "status")
    real_data = _dig(payload, "data") if isinstance(payload, dict) else None
    if real_data is None:
        real_data = payload if isinstance(payload, dict) else {}
    # G5 等接口：facade 返回的 res.data 自身仍带 {status, data:{派生字段}}，再下钻一层
    if isinstance(real_data, dict) and isinstance(real_data.get("data"), dict):
        real_data = real_data["data"]

    # status 红线：error / warning 即失败（不准假绿，warning 往往是源不可用降级）
    if status in ("error", "warning"):
        return False, f"status={status}, error={_dig(payload, 'error')}, msg={_dig(payload, 'message')}"

    # 派生字段契约断言
    missing = []
    for f in spec["must_have"]:
        # 优先在 data 层找，退而在 payload 顶层找
        if _dig(real_data, f) is None and _dig(payload, f) is None:
            missing.append(f)

    if missing:
        # 打印原始 data 前 2 行，供定位 Futu 真实列名
        sample = json.dumps(real_data, ensure_ascii=False, default=str)[:800]
        return False, (
            f"派生字段缺失 {missing}（可能是 Futu 10.10 列名与解析器预期不符）\n  └─ 原始 data 样本: {sample}"
        )

    # 通过
    return True, f"status={status}, 派生字段齐全 {spec['must_have']}"


def main() -> int:
    ap = argparse.ArgumentParser(description="S1 G-series 全链路冒烟")
    ap.add_argument("--base", default=DEFAULT_BASE, help="主服务 base URL")
    args = ap.parse_args()
    base = args.base

    section("S1 G-series 全链路冒烟")
    print(f"目标: {base}")
    print(f"覆盖: {', '.join(REQUIRED_DERIVED_FIELDS.keys())}")

    results = []
    for name, spec in REQUIRED_DERIVED_FIELDS.items():
        try:
            ok, detail = check(name, spec, base)
        except Exception:  # noqa: BLE001
            ok, detail = False, f"脚本异常: {traceback.format_exc()}"
        results.append((name, ok, detail))
        mark = "✅ PASS" if ok else "❌ FAIL"
        print(f"\n[{mark}] {name} — {spec['desc']}")
        print(f"    {detail}")

    section("汇总")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    for name, ok, _ in results:
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"\n通过 {passed}/{total}")

    if passed < total:
        print("\n⚠️ 存在失败项：检查上方 FAIL 详情中的 Futu 真实列名样本，")
        print("   回炉校准对应 facade 的防御式解析器（G4/G5/G6/G7 的列名启发式）。")
        return 1
    print("\n🎯 全部通过：五大聚合接口在 S1 真实数据下防御式解析校准无误。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
