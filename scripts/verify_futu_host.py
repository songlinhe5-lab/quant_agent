#!/usr/bin/env python3
"""
验证容器内能否经 host.docker.internal 连到宿主 Futu OpenD。

用法:
  python scripts/verify_futu_host.py                 # 用默认 host (host.docker.internal)
  FUTU_HOST=127.0.0.1 python scripts/verify_futu_host.py
  python scripts/verify_futu_host.py --host host.docker.internal --port 11111

退出码: 0=可达, 1=不可达, 2=参数/环境错误
"""

import argparse
import os
import socket
import sys

DEFAULT_HOST = os.getenv("FUTU_HOST", "host.docker.internal")
DEFAULT_PORT = int(os.getenv("FUTU_PORT", "11111"))
TIMEOUT = 3.0


def probe(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        # 先解析，确认 DNS 是否把 host.docker.internal 映射出来
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        resolved = sorted({i[4][0] for i in infos})
    except socket.gaierror as e:
        return False, f"DNS 解析失败: {host} -> {e}"

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"TCP 连通 OK ({host}:{port}) resolved={resolved}"
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        return False, f"TCP 连接失败: {host}:{port} resolved={resolved} err={e}"


def main():
    ap = argparse.ArgumentParser(description="验证 Futu OpenD 宿主机连通性")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--timeout", type=float, default=TIMEOUT)
    args = ap.parse_args()

    print(f"[verify] FUTU_HOST env  = {os.getenv('FUTU_HOST', '(unset)')}")
    print(f"[verify] 探测目标       = {args.host}:{args.port}")
    print(f"[verify] 超时           = {args.timeout}s")
    print("-" * 50)

    ok, msg = probe(args.host, args.port, args.timeout)
    status = "✅ 可达" if ok else "❌ 不可达"
    print(f"{status}  {msg}")

    if not ok:
        print("-" * 50)
        print("排查建议:")
        print("  1. 容器需有 extra_hosts: host.docker.internal:host-gateway")
        print("  2. 宿主 OpenD 监听地址应为 127.0.0.1:11111 (ss -tlnp | grep 11111)")
        print("  3. 本机裸跑时改用 FUTU_HOST=127.0.0.1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
