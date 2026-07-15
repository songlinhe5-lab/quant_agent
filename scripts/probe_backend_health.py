#!/usr/bin/env python3
"""CI 探针 — 验证 quant-api 后端接口正确性。

专为 CI / 部署后冒烟测试设计：
- 快速（默认 10s 超时，长超时接口不进探针）
- 明确退出码：0=全过 / 1=有失败 / 2=网关不可达或中断
- 支持 --json 机器可读输出、--strict 严格模式（任何失败均非零退出）

用法:
  BACKEND_API_URL=https://quant-api.stephenhe.com/api/v1 \
    uv run python scripts/probe_backend_health.py
  uv run python scripts/probe_backend_health.py --json --strict
  uv run python scripts/probe_backend_health.py --url http://127.0.0.1:8000/api/v1
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.stderr.write("依赖缺失: 请先安装 httpx (uv pip install httpx)\n")
    sys.exit(2)


class C:
    HEADER = "\033[95m"
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    END = "\033[0m"
    CYAN = "\033[96m"


# 检查项定义:
#   name     : 人类可读名称
#   path     : 相对 /api/v1 的路径（不含前缀）
#   params   : 查询参数
#   auth_ok  : True 表示 401/403 视为通过（鉴权端点，路由存在即正确）
#   critical : True 表示失败即判定部署异常（基础设施级，影响退出码）
CHECKS = [
    # ---- 健康基线（部署后最先探，502 即网关未就绪）----
    {"name": "数据源健康", "path": "/data-source/health", "params": {}, "critical": True},
    {"name": "Futu 诊断", "path": "/futu/diagnose", "params": {}, "critical": True},
    # ---- 鉴权生效验证（401 = 路由存在且鉴权正确）----
    {"name": "内部健康(鉴权)", "path": "/internal/health", "params": {}, "auth_ok": True},
    {"name": "用户偏好(鉴权)", "path": "/settings/preferences", "params": {}, "auth_ok": True},
    # ---- 核心修复回归（本轮修复的期权链 IV 路径）----
    {"name": "期权链", "path": "/market/option-chain", "params": {"ticker": "AAPL"}, "critical": True},
    {"name": "IV 排名", "path": "/options/iv-rank/AAPL", "params": {}, "critical": True},
    {"name": "波动率微笑", "path": "/options/vol-smile/AAPL", "params": {}},
    {"name": "期权 Greeks", "path": "/options/greeks/AAPL", "params": {}},
    # ---- 通用回归 ----
    {"name": "实时行情", "path": "/market/quote", "params": {"ticker": "AAPL"}},
    {"name": "宏观新闻", "path": "/macro/news", "params": {}},
    {"name": "风险仪表盘", "path": "/risk/dashboard", "params": {}},
]


def _biz_ok(data: dict) -> bool:
    """业务层是否成功：兼容 code==0 或 status 在成功集合。

    真实 API 两种风格并存：{"code": 0} 与 {"status": "ok"}，统一归一化。
    """
    if "code" in data:
        code = data["code"]
        return code in (0, "0", None)
    if "status" in data:
        return str(data["status"]).lower() in ("ok", "success", "healthy", "degraded")
    return True  # 无 status/code 字段，结构正常即视为通过


async def probe(client: httpx.AsyncClient, base: str, check: dict, strict: bool):
    path = check["path"]
    url = f"{base}{path}"
    try:
        resp = await client.get(url, params=check.get("params", {}))
    except httpx.TimeoutException:
        return path, "TIMEOUT", "请求超时(>阈值)", False
    except httpx.ConnectError:
        return path, "UNREACHABLE", "无法连接网关", False
    except Exception as e:  # pragma: no cover
        return path, "ERROR", str(e)[:80], False

    status = resp.status_code

    # 鉴权端点：401/403 视为路由存在且鉴权生效（即便带凭证 200 也通过）
    if check.get("auth_ok"):
        if status in (401, 403, 200):
            note = "鉴权生效(路由存在)" if status in (401, 403) else "200 (可能带凭证)"
            return path, status, note, True
        return path, status, f"非预期状态码: {resp.text[:80]}", False

    if status != 200:
        return path, status, f"HTTP {status}: {resp.text[:120]}", False

    # 2xx：业务层判定
    try:
        data = resp.json()
    except Exception:
        data = {}
    if isinstance(data, dict) and not _biz_ok(data):
        msg = data.get("message") or data.get("msg") or data.get("detail") or ""
        return path, status, f"业务失败: {msg}", False
    return path, status, "OK", True


async def run(base: str, strict: bool, as_json: bool) -> int:
    results = []
    gw_ok = True
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for c in CHECKS:
            path, status, msg, ok = await probe(client, base, c, strict)
            results.append({
                "name": c["name"], "path": path, "http": status,
                "ok": ok, "msg": msg, "critical": c.get("critical", False),
            })
            if not ok and c.get("critical"):
                gw_ok = False

    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed

    if as_json:
        print(json.dumps(
            {"base": base, "passed": passed, "failed": failed, "results": results},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(f"\n{C.BOLD}{C.HEADER}🔍 后端接口 CI 探针  (Target: {base}){C.END}\n")
        for r in results:
            mark = f"{C.OK}✅" if r["ok"] else f"{C.FAIL}❌"
            crit = f"{C.WARN}[关键]{C.END}" if r["critical"] else "       "
            print(f"{mark} {crit} {C.CYAN}{r['name']:<14}{C.END} "
                  f"HTTP {str(r['http']):<4} {r['msg']}")
        print(f"\n{C.BOLD}通过 {passed}/{len(results)} | 失败 {failed}{C.END}")

    if not gw_ok:
        print(f"{C.FAIL}💥 存在关键基础设施级失败 (健康基线/核心修复未通过){C.END}")
        return 1
    if failed:
        print(f"{C.WARN}⚠️  存在非关键失败项{C.END}")
        return 1 if strict else 0
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="quant-api 后端接口 CI 探针")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--strict", action="store_true", help="任何失败均非零退出")
    ap.add_argument("--url", default=None, help="覆盖 BACKEND_API_URL")
    args = ap.parse_args()

    base = (args.url or os.getenv(
        "BACKEND_API_URL", "https://quant-api.stephenhe.com/api/v1"
    )).rstrip("/")
    try:
        rc = asyncio.run(run(base, args.strict, args.json))
    except KeyboardInterrupt:  # pragma: no cover
        print("\n[中断]")
        rc = 2
    sys.exit(rc)


if __name__ == "__main__":
    main()
