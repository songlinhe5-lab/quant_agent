#!/usr/bin/env python3
# ==========================================
# Quant Agent - 主服务器全量后端接口有效性验证
# ==========================================
# 直接从主服务器拉取 /openapi.json (真实运行态路由表)，对 247 个接口逐个发请求，
# 按状态码分类: 200 正常 / 401·403 鉴权生效 / 404 设计性无数据 / 422 参数问题 /
#               5xx 真实服务端错误 / 连接错误。输出每接口结果 + 汇总 + JSON 报告。
#
# 用法:
#   python scripts/verify_all_api_endpoints.py
#   python scripts/verify_all_api_endpoints.py --base https://quant-api.stephenhe.com
# ==========================================

import argparse
import json
import sys
import time
from urllib.parse import urljoin

try:
    import httpx
except ImportError:
    print("缺少 httpx，请先: pip install httpx", file=sys.stderr)
    sys.exit(2)


def fetch_openapi(base: str, timeout: float):
    url = urljoin(base + "/", "openapi.json")
    r = httpx.get(url, timeout=timeout, verify=False)
    r.raise_for_status()
    return r.json()


def collect_operations(spec):
    ops = []
    paths = spec.get("paths", {})
    for path, methods in paths.items():
        for method, meta in methods.items():
            method = method.upper()
            if method in ("OPTIONS", "TRACE", "HEAD"):
                continue
            ops.append(
                {
                    "method": method,
                    "path": path,
                    "op_id": meta.get("operationId", ""),
                    "summary": meta.get("summary", "") or meta.get("description", ""),
                }
            )
    return ops


def classify(status: int) -> str:
    if status == 0:
        return "CONN_ERR"
    if 200 <= status < 300:
        return "OK"
    if status in (401, 403):
        return "AUTH_REQUIRED"
    if status == 404:
        return "NOT_FOUND"
    if status == 405:
        return "METHOD_NOT_ALLOWED"
    if status == 422:
        return "VALIDATION_ERR"
    if 400 <= status < 500:
        return "CLIENT_ERR"
    if 500 <= status < 600:
        return "SERVER_ERR"
    return f"HTTP_{status}"


# 对写接口给的最小合法 JSON，减少 422 误报
SAMPLE_BODY = {"symbol": "AAPL", "action": "QUOTE"}


def main():
    parser = argparse.ArgumentParser(description="主服务器全量后端接口有效性验证")
    parser.add_argument("--base", default="http://100.102.223.44:8000")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print("=== 主服务器全量接口冒烟验证 ===")
    print(f"Target : {base}")

    # 1) 拉取 OpenAPI
    try:
        spec = fetch_openapi(base, args.timeout)
    except Exception as e:
        print(f"[FATAL] 无法拉取 {base}/openapi.json: {e}", file=sys.stderr)
        sys.exit(1)

    ops = collect_operations(spec)
    print(f"接口总数: {len(ops)}\n")

    # 2) 逐个探测
    counts = {}
    results = []
    real_errors = []

    with httpx.Client(base_url=base, timeout=args.timeout, follow_redirects=True, verify=False) as client:
        for op in ops:
            method, path = op["method"], op["path"]
            status = 0
            detail = ""
            try:
                if method == "GET":
                    resp = client.get(path)
                elif method == "POST":
                    try:
                        resp = client.post(path, json=SAMPLE_BODY)
                    except Exception:
                        resp = client.post(path)
                elif method == "PUT":
                    resp = client.put(path, json=SAMPLE_BODY)
                elif method == "DELETE":
                    resp = client.request("DELETE", path)
                elif method == "PATCH":
                    resp = client.patch(path, json=SAMPLE_BODY)
                else:
                    resp = client.request(method, path)
                status = resp.status_code
                try:
                    j = resp.json()
                    if isinstance(j, dict):
                        d = j.get("detail") or j.get("msg") or j.get("message")
                        if isinstance(d, list):
                            d = str(d[:1])
                        detail = str(d)[:90]
                except Exception:
                    pass
            except httpx.ConnectError:
                detail = "connection refused"
            except httpx.TimeoutException:
                detail = f"timeout>{args.timeout}s"
            except Exception as e:
                detail = str(e)[:90]

            tag = classify(status)
            counts[tag] = counts.get(tag, 0) + 1
            rec = {"method": method, "path": path, "status": status, "tag": tag, "detail": detail, "op_id": op["op_id"]}
            results.append(rec)

            if tag in ("SERVER_ERR", "CONN_ERR", "METHOD_NOT_ALLOWED"):
                real_errors.append(rec)
                print(f"  [{tag}] {method:>6} {path} -> {status} {detail}")
            elif args.verbose and tag not in ("OK",):
                print(f"  [{tag}] {method:>6} {path} -> {status} {detail}")

    # 3) 汇总
    print("\n=== 汇总 ===")
    order = [
        "OK",
        "AUTH_REQUIRED",
        "NOT_FOUND",
        "VALIDATION_ERR",
        "CLIENT_ERR",
        "METHOD_NOT_ALLOWED",
        "SERVER_ERR",
        "CONN_ERR",
    ]
    for k in order:
        if k in counts:
            print(f"  {k:>16}: {counts[k]}")
    total = sum(counts.values())
    print(f"  {'TOTAL':>16}: {total}")

    if real_errors:
        print(f"\n!!! 需关注: {len(real_errors)} 个接口返回 5xx/连接错误 !!!")
        for r in real_errors:
            print(f"  {r['method']:>6} {r['path']} -> {r['status']} {r['detail']}")
    else:
        print("\n✓ 无 5xx 服务端错误或连接错误，所有接口路由层可达。")

    report = {
        "target": base,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": total,
        "counts": counts,
        "results": results,
    }
    out = "scripts/api_smoke_report.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n报告已写出: {out}")

    sys.exit(1 if real_errors else 0)


if __name__ == "__main__":
    main()
